import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Project folders
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
INDEX_DIR = Path(os.getenv("INDEX_DIR", ROOT / "index"))


# ---------------------------------------------------------------------------
# .env loader  (read once at import time)
# ---------------------------------------------------------------------------

_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def csv(name: str, default: str = "") -> list[str]:
    """Return a cleaned list from a comma-separated environment variable."""
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# Supabase Postgres — use the "session pooler" connection string.
DATABASE_URL = os.getenv("DATABASE_URL", "")


# ---------------------------------------------------------------------------
# LLM providers  (OpenRouter)
# ---------------------------------------------------------------------------

OPENROUTER_URL = "https://openrouter.ai/api/v1"

# Main key first, then backup keys.
OPENROUTER_KEYS = list(
    dict.fromkeys(csv("OPENROUTER_API_KEY") + csv("OPENROUTER_API_KEYS"))
)

MODELS = csv(
    "OPENROUTER_MODELS",
    "nvidia/nemotron-3-super-120b-a12b:free,"
    "openai/gpt-oss-120b:free,"
    "google/gemma-4-31b-it:free,"
    "openrouter/free",
)

DISCOVER_FREE_MODELS = os.getenv("DISCOVER_FREE_MODELS", "1") == "1"
KEY_COOLDOWN_SECONDS = int(os.getenv("KEY_COOLDOWN_SECONDS", "3600"))


# ---------------------------------------------------------------------------
# Optional fallback provider  (any OpenAI-compatible API)
# ---------------------------------------------------------------------------

FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", "").rstrip("/")
FALLBACK_KEYS = csv("FALLBACK_API_KEY")
FALLBACK_MODELS = csv("FALLBACK_MODELS")


# ---------------------------------------------------------------------------
# Search / embeddings
# ---------------------------------------------------------------------------

EMBED_MODEL = os.getenv(
    "EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
USE_DENSE = os.getenv("USE_DENSE", "1") == "1"
TOP_K = int(os.getenv("TOP_K", "6"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "900"))


# ---------------------------------------------------------------------------
# Web app
# ---------------------------------------------------------------------------

MAX_MESSAGE_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "1000"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "8"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "12"))
PORT = int(os.getenv("PORT", "7860"))
