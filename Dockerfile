FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    PORT=7860

# Hugging Face Spaces runs containers as UID 1000
RUN useradd -m -u 1000 user
WORKDIR /app

# dependencies first (cached layer)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

COPY src ./src
COPY data ./data

# at build time: download the embedding model and build a local backup index
# (the main index lives in Supabase, built with: python -m rag.indexing)
RUN python -c "from rag import embeddings; assert embeddings.available()" \
 && python -m rag.indexing --source local --target local \
 && chown -R user:user /app

USER user
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
