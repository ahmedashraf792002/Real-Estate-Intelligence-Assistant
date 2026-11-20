import numpy as np

from rag import database, indexing


def chunk(url, i, text):
    return {"url": url, "chunk_index": i, "source": "S", "title": "T " + url, "text": text}


def test_documents_upsert_and_load(db):
    docs = [{"url": "u1", "source": "A", "title": "One", "text": "x" * 120}, {"url": "u1", "source": "A", "title": "dup", "text": "y"}]
    assert database.save_documents(docs) == 1
    database.save_documents([{"url": "u1", "source": "A", "title": "Changed", "text": "z" * 120}])
    rows, origin = database.load_documents()
    assert origin == "database" and len(rows) == 1 and rows[0]["title"] == "Changed"


def test_projects_roundtrip(db):
    database.save_projects([{"id": 5, "name": "Shams", "units": [1, 2]}, {"id": 5, "name": "Shams", "units": [1, 2]}, {"name": "no id"}])
    assert database.load_projects() == [{"id": 5, "name": "Shams", "units": [1, 2]}]


def test_index_save_load_and_vector_search(db):
    chunks = [chunk("a", 0, "alpha"), chunk("b", 0, "beta"), chunk("c", 0, "gamma")]
    vectors = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype="float32")
    index = database.DatabaseIndex()
    # the schema uses 384 dimensions, so pad the test vectors
    padded = np.zeros((3, 384), dtype="float32")
    padded[:, :3] = vectors
    index.save(chunks, padded, {"dense": True, "built_at": "2026-11-20"})

    loaded = index.load_chunks()
    assert [c["url"] for c in loaded] == ["a", "b", "c"] and index.has_vectors()
    query = np.zeros(384, dtype="float32")
    query[1] = 1
    best_id, score = index.search(query, 2)[0]
    assert best_id == loaded[1]["id"] and score > 0.99


def test_saving_again_replaces_old_chunks(db):
    index = database.DatabaseIndex()
    index.save([chunk("a", 0, "old"), chunk("b", 0, "old")], None, {"dense": False})
    index.save([chunk("c", 0, "new")], None, {"dense": False})
    assert [c["url"] for c in index.load_chunks()] == ["c"] and not index.has_vectors()


def test_indexing_from_database_to_database(db):
    docs = [{"url": f"https://x/{i}", "source": "S", "title": f"Villa {i}", "text": f"Villa number {i} in Dubai. " * 20} for i in range(3)]
    database.save_documents(docs)
    meta = indexing.build_index("database", ("database",))
    index, chunks = database.open_index()
    assert index.name == "database" and len(chunks) == meta["chunks"] >= 3
