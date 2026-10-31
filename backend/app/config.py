"""App settings, read from environment variables (or a local .env file)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# "ollama" (local model, no key needed) or "gemini" (Google API, needs GEMINI_API_KEY).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# Must be a vision-capable model, e.g. gemma4:26b, qwen2.5vl:7b, llava:7b.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:26b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Model names and free-tier quotas change often; run scripts/list_models.py to see what your key can use.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Tried in order when the main model is overloaded (503), out of quota (429) or retired (404).
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-flash-lite-latest").split(",")
    if m.strip()
]
# Retries per model for transient errors (503/500/504), with 1s, 2s, ... backoff.
GEMINI_RETRIES = int(os.getenv("GEMINI_RETRIES", "2"))

# Vercel's filesystem is read-only except /tmp, which is wiped between instances:
# meals logged there are lost unpredictably (demo use only).
_DEFAULT_DB = Path("/tmp/calories.db") if os.getenv("VERCEL") else BASE_DIR / "data" / "calories.db"
DB_PATH = Path(os.getenv("DB_PATH", _DEFAULT_DB))
STATIC_DIR = BASE_DIR / "static"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Images are downscaled before upload: fewer tokens, faster, and enough detail to recognise food.
MAX_IMAGE_SIDE = 1024
