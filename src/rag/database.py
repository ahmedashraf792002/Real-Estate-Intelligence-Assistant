import json

import numpy as np
import psycopg

from . import config


# one shared connection for reading, opened the first time it is needed
_conn = None


def get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(config.DATABASE_URL, autocommit=True, prepare_threshold=None)
    return _conn


def to_vector(vec):
    # pgvector text format: [0.1,0.2,...]
    return "[" + ",".join(f"{x:.6g}" for x in vec) + "]"


def read_pages():
    # every scraped page is one line in data/raw/data/*.jsonl
    docs, projects = [], []
    for path in sorted((config.DATA_DIR / "raw" / "data").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").split("\n"):  # not splitlines(): U+2028 is inside texts
            if line.strip():
                row = json.loads(line)
                project = row.pop("project", None)  # only Wasalt project rows have it
                if project:
                    projects.append(project)
                docs.append(row)
    return docs, projects


# documents and projects (the scraped dataset)

def save_documents(docs):
    # one row per url
    rows = {}
    for d in docs:
        rows.setdefault(d["url"], (d["url"], d["source"], d.get("title"), d["text"]))
    sql = """insert into documents (url, source, title, text) values (%s, %s, %s, %s)
             on conflict (url) do update set source = excluded.source, title = excluded.title,
                                             text = excluded.text, scraped_at = now()"""
    with psycopg.connect(config.DATABASE_URL, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, list(rows.values()))
    return len(rows)


def save_projects(projects):
    # one row per project id
    rows = list({p["id"]: (p["id"], json.dumps(p, ensure_ascii=False)) for p in projects if p.get("id")}.values())
    sql = """insert into projects (id, data) values (%s, %s::jsonb)
             on conflict (id) do update set data = excluded.data, updated_at = now()"""
    with psycopg.connect(config.DATABASE_URL, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    return len(rows)


def load_documents(source="auto"):
    # database first
    if source in ("auto", "database") and config.DATABASE_URL:
        try:
            rows = get_conn().execute("select url, source, title, text from documents order by url").fetchall()
            if rows:
                return [{"url": r[0], "source": r[1], "title": r[2], "text": r[3]} for r in rows], "database"
        except Exception as e:
            print("database not available:", str(e)[:150])
            if source == "database":
                raise
    # then the scraped files
    docs = read_pages()[0]
    if not docs:
        raise SystemExit("no documents found in the database or in data/raw/data")
    return docs, "local"


def load_projects():
    if config.DATABASE_URL:
        try:
            rows = get_conn().execute("select data from projects order by id").fetchall()
            if rows:
                return [r[0] for r in rows]
        except Exception as e:
            print("database projects not available:", str(e)[:150])
    return read_pages()[1]


# chunks and vectors (the search index)

class DatabaseIndex:
    name = "database"

    def save(self, chunks, vectors, meta):
        rows = []
        for i, c in enumerate(chunks):
            vec = to_vector(vectors[i]) if vectors is not None else None
            rows.append((c["url"], c["chunk_index"], c["source"], c["title"], c["text"], vec))
        insert = """insert into chunks (url, chunk_index, source, title, text, embedding)
                    values (%s, %s, %s, %s, %s, %s::vector)"""
        meta_sql = """insert into kv (key, value) values ('index_meta', %s::jsonb)
                      on conflict (key) do update set value = excluded.value"""
        # one transaction: the old index stays visible until the new one is complete
        with psycopg.connect(config.DATABASE_URL, prepare_threshold=None) as conn:
            conn.execute("delete from chunks")
            with conn.cursor() as cur:
                cur.executemany(insert, rows)
            conn.execute(meta_sql, (json.dumps(meta),))

    def load_chunks(self):
        sql = "select id, url, chunk_index, source, title, text from chunks order by id"
        cols = ("id", "url", "chunk_index", "source", "title", "text")
        return [dict(zip(cols, r)) for r in get_conn().execute(sql).fetchall()]

    def load_meta(self):
        row = get_conn().execute("select value from kv where key = 'index_meta'").fetchone()
        return row[0] if row else {}

    def has_vectors(self):
        return bool(self.load_meta().get("dense"))

    def search(self, vec, k):
        # nearest chunks by cosine distance, returns [(chunk_id, similarity)]
        v = to_vector(vec)
        sql = """select id, 1 - (embedding <=> %s::vector) from chunks
                 where embedding is not null order by embedding <=> %s::vector limit %s"""
        return [(r[0], float(r[1])) for r in get_conn().execute(sql, (v, v, k)).fetchall()]


class LocalIndex:
    # backup copy of the index in index/ (used if the database is down)
    name = "local"

    def __init__(self):
        self.ids = []
        self.vectors = None

    def save(self, chunks, vectors, meta):
        config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
        rows = [{**c, "id": i} for i, c in enumerate(chunks)]
        (config.INDEX_DIR / "chunks.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        npy = config.INDEX_DIR / "embeddings.npy"
        if vectors is not None:
            np.save(npy, vectors)
        elif npy.exists():
            npy.unlink()  # old vectors would not match the new chunks
        (config.INDEX_DIR / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def load_chunks(self):
        path = config.INDEX_DIR / "chunks.json"
        chunks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        self.ids = [c["id"] for c in chunks]
        npy = config.INDEX_DIR / "embeddings.npy"
        self.vectors = np.load(npy) if chunks and npy.exists() else None
        return chunks

    def load_meta(self):
        path = config.INDEX_DIR / "meta.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def has_vectors(self):
        return self.vectors is not None

    def search(self, vec, k):
        sims = self.vectors @ vec
        return [(self.ids[i], float(sims[i])) for i in np.argsort(-sims)[:k]]


def open_index():
    # database first, local backup second. returns (index, chunks)
    indexes = [DatabaseIndex(), LocalIndex()] if config.DATABASE_URL else [LocalIndex()]
    for index in indexes:
        try:
            chunks = index.load_chunks()
        except Exception as e:
            print(f"{index.name} index not available:", str(e)[:150])
            continue
        if chunks:
            print(f"search index: {index.name} ({len(chunks)} chunks)")
            return index, chunks
    raise RuntimeError("no search index found, run: python -m rag.indexing")
