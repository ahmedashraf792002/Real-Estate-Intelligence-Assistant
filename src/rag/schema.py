# Creates the tables in Supabase Postgres. Safe to run many times (create ... if not exists).
#   python -m rag.schema      (also runs by itself before "scraper push" and "rag.indexing")
import psycopg

from . import config

TABLES = """
create extension if not exists vector;

-- scraped pages (the dataset)
create table if not exists documents (
  url        text primary key,
  source     text not null,
  title      text,
  text       text not null,
  scraped_at timestamptz default now()
);

-- Wasalt projects (used for the "cheapest / how many" catalog)
create table if not exists projects (
  id         bigint primary key,
  data       jsonb not null,
  updated_at timestamptz default now()
);

-- search index: chunks + embeddings (384 = multilingual MiniLM)
create table if not exists chunks (
  id          bigserial primary key,
  url         text not null,
  chunk_index int not null,
  source      text,
  title       text,
  text        text not null,
  embedding   vector(384),
  unique (url, chunk_index)
);
create index if not exists chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);

-- small key/value table (index info like the build date)
create table if not exists kv (
  key   text primary key,
  value jsonb not null
);

-- closes the public Supabase API for these tables (the app connects directly, so it is not affected)
alter table documents enable row level security;
alter table projects  enable row level security;
alter table chunks    enable row level security;
alter table kv        enable row level security;
"""


def create_tables(url=None):
    with psycopg.connect(url or config.DATABASE_URL, prepare_threshold=None) as conn:
        conn.execute(TABLES)
    print("tables are ready")


if __name__ == "__main__":
    create_tables()
