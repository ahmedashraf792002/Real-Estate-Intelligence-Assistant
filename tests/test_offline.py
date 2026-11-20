import json

import numpy as np

from rag import config, database, indexing
from rag.indexing import chunk_documents, clean_documents, normalize_text, split_text


def doc(url, text, source="X", title="T"):
    return {"source": source, "url": url, "title": title, "text": text}


def test_normalize_text():
    assert normalize_text("a   b\n\n\n c\u00a0d") == "a b\nc d"


def test_clean_drops_short_pages_and_duplicates():
    long = "word " * 40
    out = clean_documents([doc("u1", long), doc("u2", long), doc("u3", "tiny")])
    assert [d["url"] for d in out] == ["u1"]


def test_repeated_menu_lines_are_removed():
    docs = [doc(f"u{i}", f"Menu Home\nUnique text of page {i} " + "filler " * 30, source="DarGlobal") for i in range(30)]
    out = clean_documents(docs)
    assert len(out) == 30 and all("Menu Home" not in d["text"] for d in out)


def test_html_tags_are_removed_from_text():
    assert normalize_text("<p>Price: 5</p><p>Area &amp; size</p>") == "Price: 5\nArea & size"


def test_junk_pages_are_dropped():
    long = "word " * 40
    out = clean_documents([doc("u1", long, title="Application error: a client-side exception"),
                           doc("u2", long + "x", title="Real page")])
    assert [d["url"] for d in out] == ["u2"]


def test_wasalt_page_menus_are_removed_but_listing_lines_are_kept():
    pages = [doc(f"p{i}", f"فلل للبيع\nUnique page {i} " + "filler " * 30, source="Wasalt page") for i in range(30)]
    listings = [doc(f"l{i}", f"Purpose: sale\nPrice: {i} SAR " + "filler " * 30, source="Wasalt listing") for i in range(30)]
    out = clean_documents(pages + listings)
    assert all("فلل للبيع" not in d["text"] for d in out if d["source"] == "Wasalt page")
    assert all("Purpose: sale" in d["text"] for d in out if d["source"] == "Wasalt listing")


def test_cloudflare_pages_and_auction_follower_lines_are_dropped():
    body = "مزاد سام موتورز\n" + "هيونداي توسان 2020 السعر الافتتاحي 20,000\n" * 4
    followers = "المتابعونالأصل 3\n4 دقيقة\nالمستخدم #764615 بدأ متابعة هذا الأصل\n"
    out = clean_documents([doc("u1", body + followers, source="Wasalt auction", title="مزاد"),
                           doc("u2", "x" * 300, source="Wasalt auction", title="لحظة…")])
    assert [d["url"] for d in out] == ["u1"]
    assert "المستخدم #" not in out[0]["text"] and "المتابعون" not in out[0]["text"] and "دقيقة" not in out[0]["text"]


def test_chunks_have_size_and_index():
    text = "\n".join(f"Line number {i} with some words in it." for i in range(200))
    chunks = chunk_documents([doc("u", text)])
    assert len(chunks) > 3 and [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert max(len(c["text"]) for c in chunks) < 1100
    assert split_text("") == [""] or split_text("") == []


def test_local_index_roundtrip_and_search():
    index = database.LocalIndex()
    chunks = [{"url": "a", "chunk_index": 0, "source": "S", "title": "A", "text": "alpha"},
              {"url": "b", "chunk_index": 0, "source": "S", "title": "B", "text": "beta"}]
    index.save(chunks, np.array([[1, 0], [0, 1]], dtype="float32"), {"dense": True})
    loaded = database.LocalIndex()
    assert len(loaded.load_chunks()) == 2 and loaded.has_vectors()
    assert loaded.search(np.array([0, 1], dtype="float32"), 1)[0][0] == 1


def test_build_index_local_end_to_end():
    folder = config.DATA_DIR / "raw" / "data"
    folder.mkdir(parents=True)
    docs = [doc(f"https://x/{i}", f"Villa number {i} in Dubai. " * 20, title=f"Villa {i}") for i in range(3)]
    (folder / "pages.jsonl").write_text("\n".join(json.dumps(d) for d in docs))
    meta = indexing.build_index("local", ("local",))
    index, chunks = database.open_index()
    assert index.name == "local" and len(chunks) == meta["chunks"] and meta["dense"] is False


def test_read_pages_splits_documents_and_projects():
    folder = config.DATA_DIR / "raw" / "data"
    folder.mkdir(parents=True)
    (folder / "a.jsonl").write_text(json.dumps(doc("u1", "text one")) + "\n")
    row = {**doc("u2", "text two"), "project": {"id": 7, "name": "P"}}
    (folder / "b.jsonl").write_text(json.dumps(row) + "\n\n")
    docs, projects = database.read_pages()
    assert [d["url"] for d in docs] == ["u1", "u2"] and "project" not in docs[1]
    assert projects == [{"id": 7, "name": "P"}]
