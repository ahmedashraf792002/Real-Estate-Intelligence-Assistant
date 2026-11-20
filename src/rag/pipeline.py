# Online part of the RAG: question -> search -> prompt -> model -> answer with sources
from . import config, database, embeddings, generation
from .retrieval import Retriever


def build_catalog(projects):
    # one line per Wasalt project, always sent to the model ("cheapest", "how many"...)
    lines = []
    for p in projects:
        if p.get("price_min"):
            price = f"{p['price_min']:,}-{(p.get('price_max') or p['price_min']):,} {p.get('currency') or ''}".strip()
        else:
            price = "price n/a"
        lines.append(f"- {p.get('name')} | developer: {p.get('developer') or 'n/a'} | {p.get('city')}, {p.get('district')} | "
                     f"{price} | units available: {p.get('units_available')} | {', '.join(p.get('status') or [])}")
    return "\n".join(lines)


class Pipeline:
    def __init__(self, retriever, catalog="", meta=None, llm=generation, backend="?"):
        self.retriever = retriever
        self.catalog = catalog
        self.meta = meta or {}
        self.llm = llm  # anything with stream_chat(messages)
        self.backend = backend

    @classmethod
    def from_env(cls):
        index, chunks = database.open_index()
        meta = index.load_meta()
        use_vectors = config.USE_DENSE and meta.get("dense") and embeddings.available()
        retriever = Retriever(chunks, index, embeddings.embed_query if use_vectors else None)
        try:
            catalog = build_catalog(database.load_projects())
        except Exception as e:
            print("project catalog not available:", str(e)[:150])
            catalog = ""
        return cls(retriever, catalog, meta, backend=index.name)

    @staticmethod
    def search_query(history):
        # a short follow-up like "and the price?" also uses the previous question
        users = [m["content"] for m in history if m["role"] == "user"]
        if len(users[-1]) < 30 and len(users) > 1:
            return users[-2] + " " + users[-1]
        return users[-1]

    def stream(self, history, api_key=None, model=None):
        # 1. search
        try:
            found = self.retriever.search(self.search_query(history))
        except Exception as e:
            print("search error:", e)
            yield {"type": "error", "message": "The knowledge base is temporarily unavailable. Please try again in a moment."}
            yield {"type": "done"}
            return
        sources = [{"title": c["title"], "url": c["url"], "source": c["source"]} for c in found]
        yield {"type": "sources", "sources": sources}

        # 2. prompt + model
        messages = generation.build_messages(history, found, self.catalog, self.meta.get("built_at"))
        try:
            if api_key or model:
                events = self.llm.stream_chat(messages, api_key=api_key or None, model=model or None)
            else:
                events = self.llm.stream_chat(messages)
            for kind, value in events:
                yield {"type": "model", "model": value} if kind == "model" else {"type": "delta", "text": value}
        except Exception as e:
            print("model error:", e)
            yield {"type": "error", "message": "The language models are busy right now. Please try again in a moment."}
        yield {"type": "done"}
