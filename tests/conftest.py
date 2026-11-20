import os

import psycopg
import pytest

from rag import config, schema


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    # tests never use the real database, data folder or model
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "USE_DENSE", False)
    monkeypatch.setattr(config, "DISCOVER_FREE_MODELS", False)


@pytest.fixture
def db(monkeypatch):
    # a real postgres + pgvector, only when TEST_DATABASE_URL is set
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run the database tests")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop table if exists chunks, documents, projects, kv cascade")
    schema.create_tables(url)
    from rag import database
    monkeypatch.setattr(config, "DATABASE_URL", url)
    monkeypatch.setattr(database, "_conn", None)
    return url


@pytest.fixture(autouse=True)
def _no_dead_file(tmp_path, monkeypatch):
    # the fetcher remembers 404 links in a file: tests must not write into the real data folder
    from scraper import fetcher
    monkeypatch.setattr(fetcher, "DEAD_FILE", tmp_path / "dead_urls.txt")
