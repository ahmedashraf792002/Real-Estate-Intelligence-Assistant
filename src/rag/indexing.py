# Offline part of the RAG: load -> clean -> chunk -> embed -> store
#   python -m rag.indexing
#   python -m rag.indexing --source local --target local
import argparse
import hashlib
import html
import re
import time
from collections import Counter

from . import config, database, embeddings, schema


# clean

TAGS = re.compile(r"</?(?:p|br|div|span|strong|b|i|em|ul|ol|li|h[1-6])\b[^>]*>", re.I)
# pages that carry no knowledge (error pages, payment/thank-you screens)
JUNK_TITLES = ("application error", "payment successful", "thank you", "لحظة", "just a moment")  # last two: Cloudflare check
# auction pages list who follows which asset ("المستخدم #123 بدأ متابعة هذا الأصل"): user numbers, no knowledge
FOLLOWER_LINE = re.compile(r"^(?:المستخدم #\d+ .*|المتابعون.*|\d+ (?:دقيقة|ساعة|يوم))$")


def normalize_text(text):
    text = html.unescape(TAGS.sub("\n", text))  # wasalt listing descriptions contain raw <p> tags
    text = text.replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def remove_repeated_lines(docs, source="DarGlobal"):
    # menu and footer lines repeat on every page of the same site
    pages = [d for d in docs if d["source"] == source]
    if len(pages) < 20:
        return docs
    seen = Counter()
    for d in pages:
        seen.update({line for line in d["text"].split("\n")})
    limit = max(8, int(0.08 * len(pages)))
    for d in pages:
        lines = [x for x in d["text"].split("\n") if not (len(x) < 150 and seen[x] >= limit)]
        d["text"] = "\n".join(lines)
    return docs


def clean_documents(docs):
    docs = [{**d, "text": normalize_text(d.get("text") or "")} for d in docs]
    for d in docs:
        if d["source"] == "Wasalt auction":
            d["text"] = "\n".join(x for x in d["text"].split("\n") if not FOLLOWER_LINE.match(x))
    # menu / footer lines repeat on every page of these sources (not on listings: their template lines are data)
    for source in ("DarGlobal", "Wasalt page"):
        docs = remove_repeated_lines(docs, source)
    # drop short pages, error pages and exact duplicates
    out, seen = [], set()
    for d in docs:
        key = hashlib.sha1(d["text"].encode("utf-8")).hexdigest()
        if len(d["text"]) < 100 or key in seen or (d.get("title") or "").lower().startswith(JUNK_TITLES):
            continue
        seen.add(key)
        d["title"] = (d.get("title") or d["url"]).strip()
        out.append(d)
    return out


# chunk

def split_text(text, max_chars=config.CHUNK_CHARS):
    # cut long lines into sentences
    parts = []
    for line in text.split("\n"):
        pieces = re.split(r"(?<=[.!?؟])\s+", line) if len(line) > max_chars * 1.4 else [line]
        for p in pieces:
            while len(p) > 1500:
                parts.append(p[:1500])
                p = p[1500:]
            parts.append(p)
    # join the pieces into chunks, repeating the last short line as overlap
    chunks, current = [], ""
    for p in parts:
        if current and len(current) + len(p) + 1 > max_chars:
            chunks.append(current)
            last = current.split("\n")[-1]
            current = (last + "\n" if len(last) < 200 and last != p else "") + p
        else:
            current = current + "\n" + p if current else p
    if current:
        chunks.append(current)
    return chunks


def chunk_documents(docs):
    chunks = []
    for d in docs:
        pieces = [c for c in split_text(d["text"]) if len(c) >= 60]
        for i, text in enumerate(pieces):
            chunks.append({"source": d["source"], "url": d["url"], "title": d["title"], "chunk_index": i, "text": text})
    return chunks


# build

def build_index(source="auto", targets=("local",)):
    start = time.time()
    docs, origin = database.load_documents(source)
    docs = clean_documents(docs)
    chunks = chunk_documents(docs)
    print(f"{origin}: {len(docs)} documents -> {len(chunks)} chunks", dict(Counter(c["source"] for c in chunks)))

    # embeddings (skipped if the model can not be loaded)
    vectors = None
    if config.USE_DENSE and embeddings.available():
        vectors = embeddings.embed_chunks(chunks)
        print("embeddings:", vectors.shape)
    meta = {"documents": len(docs), "chunks": len(chunks), "dense": vectors is not None,
            "built_at": time.strftime("%Y-%m-%d")}

    # store (make sure the tables exist first)
    if "database" in targets:
        schema.create_tables()
    for name in targets:
        index = database.DatabaseIndex() if name == "database" else database.LocalIndex()
        index.save(chunks, vectors, meta)
        print("saved index to", name)
    print(f"done in {time.time() - start:.0f}s")
    return meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["auto", "database", "local"], default="auto")
    parser.add_argument("--target", choices=["auto", "database", "local", "both"], default="auto")
    args = parser.parse_args()
    if args.target == "local":
        targets = ("local",)
    elif args.target == "database":
        targets = ("database",)
    else:  # auto or both
        targets = ("database", "local") if config.DATABASE_URL else ("local",)
    build_index(args.source, targets)


if __name__ == "__main__":
    main()
