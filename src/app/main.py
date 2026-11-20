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

STATIC = Path(__file__).parent / "static"
requests_by_ip = defaultdict(deque)


@asynccontextmanager
async def lifespan(app):
    # load the search index once when the server starts
    try:
        app.state.pipeline = Pipeline.from_env()
    except Exception as e:
        print("could not load the search index:", e)
        app.state.pipeline = None
    yield


app = FastAPI(title="DarGlobal & Wasalt Assistant", lifespan=lifespan)


class ChatIn(BaseModel):
    messages: list
    api_key: str = ""
    model: str = ""


def check_rate_limit(request: Request):
    ip = (request.headers.get("x-forwarded-for") or request.client.host or "?").split(",")[0].strip()
    now = time.time()
    recent = requests_by_ip[ip]
    while recent and now - recent[0] > 60:
        recent.popleft()
    if len(recent) >= config.RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "Too many requests, please wait a minute.")
    recent.append(now)


def clean_history(messages):
    # keep only valid user/assistant messages, cut the length
    history = []
    for m in messages[-config.MAX_HISTORY:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip():
            history.append({"role": m["role"], "content": m["content"][:config.MAX_MESSAGE_CHARS]})
    if not history or history[-1]["role"] != "user":
        raise HTTPException(400, "The last message must be from the user.")
    return history


@app.get("/health")
def health(request: Request):
    p = request.app.state.pipeline
    return {"status": "ok" if p else "no_index",
            "index": p.backend if p else None,
            "chunks": len(p.retriever.chunks) if p else 0,
            "vector_search": bool(p and p.retriever.dense),
            "data_snapshot": p.meta.get("built_at") if p else None,
            "api_keys": len(generation.get_providers())}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    pipeline = request.app.state.pipeline
    if pipeline is None:
        raise HTTPException(503, "The knowledge base is not loaded. Run: python -m rag.indexing")
    check_rate_limit(request)
    history = clean_history(body.messages)

    def events():
        for event in pipeline.stream(history, api_key=body.api_key.strip(), model=body.model.strip()):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/models")
def free_models(api_key: str = ""):
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
            modalities = (model.get("architecture") or {}).get("output_modalities") or ["text"]
            free = str(pricing.get("prompt")) in ("0", "0.0") and str(pricing.get("completion")) in ("0", "0.0")
            name = model.get("id", "")
            if free and modalities == ["text"] and (model.get("context_length") or 0) >= 32000:
                result.append({"id": name, "name": name, "context": model.get("context_length") or 0})
        return {"models": result[:30]}
    except Exception:
        return {"models": list(dict.fromkeys(generation.config.MODELS + generation.discover_free_models()))}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
