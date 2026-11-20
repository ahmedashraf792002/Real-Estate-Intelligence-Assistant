"""Online part of the RAG pipeline: question → search → prompt → model → answer with sources."""

from . import config, database, embeddings, generation
from .retrieval import Retriever


# ---------------------------------------------------------------------------
# Lazy embedding wrapper
# ---------------------------------------------------------------------------

def _lazy_embed(text: str):
    """Load the embedding model on first call, then delegate to embed_query.

    This prevents the model from being loaded during container startup,
    which avoids OOM kills on memory-constrained deployments.
    """
    if not embeddings.available():
        raise RuntimeError("Embedding model could not be loaded; falling back to keyword search.")
    return embeddings.embed_query(text)



# ---------------------------------------------------------------------------
# Catalog builder
# ---------------------------------------------------------------------------

def build_catalog(projects: list) -> str:
    """Build a one-line-per-project summary for the LLM system prompt.

    The catalog is always sent to the model so it can answer questions like
    "cheapest project" or "how many units".
    """
    lines = []
    for p in projects:
        if p.get("price_min"):
            price = (
                f"{p['price_min']:,}-{(p.get('price_max') or p['price_min']):,} "
                f"{p.get('currency') or ''}"
            ).strip()
        else:
            price = "price n/a"

        lines.append(
            f"- {p.get('name')} "
            f"| developer: {p.get('developer') or 'n/a'} "
            f"| {p.get('city')}, {p.get('district')} "
            f"| {price} "
            f"| units available: {p.get('units_available')} "
            f"| {', '.join(p.get('status') or [])}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Pipeline:
    """Wraps the retriever and language model into a single streaming interface."""

    def __init__(self, retriever, catalog="", meta=None, llm=generation, backend="?"):
        self.retriever = retriever
        self.catalog = catalog
        self.meta = meta or {}
        self.llm = llm          # anything with stream_chat(messages)
        self.backend = backend

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "Pipeline":
        """Create a Pipeline from environment variables and the on-disk index.

        The embedding model is intentionally NOT loaded here — it is loaded
        lazily on the first search request to avoid OOM during container startup.
        """
        index, chunks = database.open_index()
        meta = index.load_meta()

        # Pass the index and a deferred embed function so the model is loaded
        # on demand (first query) rather than at startup.
        use_dense_config = config.USE_DENSE and meta.get("dense")
        retriever = Retriever(
            chunks,
            index,
            _lazy_embed if use_dense_config else None,
        )

        try:
            catalog = build_catalog(database.load_projects())
        except Exception as e:
            print("project catalog not available:", str(e)[:150])
            catalog = ""

        return cls(retriever, catalog, meta, backend=index.name)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @staticmethod
    def search_query(history: list) -> str:
        """Return the effective search query for the current turn.

        A short follow-up like "and the price?" is combined with the
        previous user message to give the retriever enough context.
        """
        users = [m["content"] for m in history if m["role"] == "user"]
        if len(users[-1]) < 30 and len(users) > 1:
            return users[-2] + " " + users[-1]
        return users[-1]

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(self, history: list, api_key: str = None, model: str = None):
        """Yield SSE-style event dicts: sources → delta* → done (or error)."""

        # 1. Retrieve relevant chunks -----------------------------------
        try:
            found = self.retriever.search(self.search_query(history))
        except Exception as e:
            print("search error:", e)
            yield {
                "type": "error",
                "message": "The knowledge base is temporarily unavailable. Please try again in a moment.",
            }
            yield {"type": "done"}
            return

        sources = [
            {"title": c["title"], "url": c["url"], "source": c["source"]}
            for c in found
        ]
        yield {"type": "sources", "sources": sources}

        # 2. Build prompt and stream model response --------------------
        messages = generation.build_messages(
            history, found, self.catalog, self.meta.get("built_at")
        )

        try:
            if api_key or model:
                events = self.llm.stream_chat(
                    messages,
                    api_key=api_key or None,
                    model=model or None,
                )
            else:
                events = self.llm.stream_chat(messages)

            for kind, value in events:
                if kind == "model":
                    yield {"type": "model", "model": value}
                else:
                    yield {"type": "delta", "text": value}

        except Exception as e:
            print("model error:", e)
            yield {
                "type": "error",
                "message": "The language models are busy right now. Please try again in a moment.",
            }

        yield {"type": "done"}
