import json
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rag import config, generation
from rag.pipeline import Pipeline

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATIC = Path(__file__).parent / "static"
requests_by_ip: dict[str, deque] = defaultdict(deque)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    """Load the search index once when the server starts."""
    try:
        app.state.pipeline = Pipeline.from_env()
    except Exception as e:
        print("could not load the search index:", e)
        app.state.pipeline = None
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="DarGlobal & Wasalt Assistant", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatIn(BaseModel):
    messages: list
    api_key: str = ""
    model: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_rate_limit(request: Request) -> None:
    """Raise HTTP 429 if the client has exceeded the per-minute request limit."""
    ip = (
        request.headers.get("x-forwarded-for")
        or request.client.host
        or "?"
    ).split(",")[0].strip()

    now = time.time()
    recent = requests_by_ip[ip]

    while recent and now - recent[0] > 60:
        recent.popleft()

    if len(recent) >= config.RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "Too many requests, please wait a minute.")

    recent.append(now)


def clean_history(messages: list) -> list:
    """Keep only valid user/assistant messages and enforce length limits."""
    history = []

    for m in messages[-config.MAX_HISTORY :]:
        is_valid_role = isinstance(m, dict) and m.get("role") in ("user", "assistant")
        is_valid_content = isinstance(m.get("content"), str) and m["content"].strip()

        if is_valid_role and is_valid_content:
            history.append({
                "role": m["role"],
                "content": m["content"][: config.MAX_MESSAGE_CHARS],
            })

    if not history or history[-1]["role"] != "user":
        raise HTTPException(400, "The last message must be from the user.")

    return history


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health(request: Request):
    p = request.app.state.pipeline
    return {
        "status": "ok" if p else "no_index",
        "index": p.backend if p else None,
        "chunks": len(p.retriever.chunks) if p else 0,
        "vector_search": bool(p and p.retriever.dense),
        "data_snapshot": p.meta.get("built_at") if p else None,
        "api_keys": len(generation.get_providers()),
    }


@app.get("/api/models")
def free_models(api_key: str = ""):
    """Return the list of free OpenRouter models available to the caller."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        r = generation.requests.get(
            f"{generation.config.OPENROUTER_URL}/models",
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()

        result = []
        for model in r.json().get("data", []):
            pricing = model.get("pricing") or {}
            modalities = (
                (model.get("architecture") or {}).get("output_modalities") or ["text"]
            )
            is_free = (
                str(pricing.get("prompt")) in ("0", "0.0")
                and str(pricing.get("completion")) in ("0", "0.0")
            )
            name = model.get("id", "")
            has_enough_context = (model.get("context_length") or 0) >= 32000

            if is_free and modalities == ["text"] and has_enough_context:
                result.append({
                    "id": name,
                    "name": name,
                    "context": model.get("context_length") or 0,
                })

        return {"models": result[:30]}

    except Exception:
        fallback = list(
            dict.fromkeys(generation.config.MODELS + generation.discover_free_models())
        )
        return {"models": fallback}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    pipeline = request.app.state.pipeline
    if pipeline is None:
        raise HTTPException(
            503,
            "The knowledge base is not loaded. Run: python -m rag.indexing",
        )

    check_rate_limit(request)
    history = clean_history(body.messages)

    def events():
        for event in pipeline.stream(
            history,
            api_key=body.api_key.strip(),
            model=body.model.strip(),
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Static files  (must come last so the routes above take priority)
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC), name="static")
