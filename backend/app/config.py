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
# Not gemini-flash-latest: in Nov 2026 it took 49-233 s per meal photo, past Vercel's 60 s limit;
# gemini-3.5-flash took 9-14 s with similar estimates.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# Tried in order when the main model is overloaded (503), out of quota (429), retired (404) or too slow.
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest").split(",")
    if m.strip()
]
# Retries per model for transient errors (503/500/504), with 1s, 2s, ... backoff.
GEMINI_RETRIES = int(os.getenv("GEMINI_RETRIES", "2"))
# Seconds one call may take before the next model is tried, and for all attempts together.
# The deadline keeps the request inside Vercel's 60 s maxDuration (with upload and start-up),
# so the user gets a clear error instead of the platform's plain-text timeout page.
GEMINI_ATTEMPT_TIMEOUT = float(os.getenv("GEMINI_ATTEMPT_TIMEOUT", "25"))
GEMINI_DEADLINE = float(os.getenv("GEMINI_DEADLINE", "45"))

# Supabase project URL, e.g. https://xyz.supabase.co (used to fetch the JWKS for ES256/RS256 tokens).
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
# Legacy HS256 JWT secret; leave empty if the project signs tokens with asymmetric keys.
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
# Publishable (anon) key, safe for clients; used for auth calls made on behalf of users.
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
# Service-role key bypasses RLS: used only by app/cron.py and the scripts, never by request handlers.
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
# Seconds to wait on Supabase HTTP calls.
SUPABASE_TIMEOUT = float(os.getenv("SUPABASE_TIMEOUT", "10"))

# Daily job (Vercel Cron sends "Authorization: Bearer <CRON_SECRET>") and web push (VAPID).
CRON_SECRET = os.getenv("CRON_SECRET", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
# A mailto: address the push services can contact, e.g. mailto:you@example.com.
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "")


def push_configured() -> bool:
    """Web push needs all three VAPID settings; with any missing it is off."""
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and VAPID_SUBJECT)


# "Today" for check-in due dates and reminders.
TIMEZONE = "Asia/Yangon"

STATIC_DIR = BASE_DIR / "static"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Images are downscaled before upload: fewer tokens, faster, and enough detail to recognise food.
MAX_IMAGE_SIDE = 1024
