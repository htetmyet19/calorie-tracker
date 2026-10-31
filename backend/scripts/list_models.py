"""List Gemini models your API key can call for content generation.

Usage: .venv/bin/python scripts/list_models.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google import genai  # noqa: E402

from app import config  # noqa: E402

if not config.GEMINI_API_KEY:
    sys.exit("GEMINI_API_KEY is not set in .env")

client = genai.Client(api_key=config.GEMINI_API_KEY)
for m in client.models.list():
    if "generateContent" in (m.supported_actions or []):
        print(m.name.removeprefix("models/"))
