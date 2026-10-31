"""Sends a meal photo to a local Ollama vision model and gets back structured nutrition estimates."""
import base64

import httpx
from pydantic import ValidationError

from . import config
from .analysis import AnalysisError
from .schemas import MealAnalysis


async def generate(image: bytes, prompt: str) -> MealAnalysis:
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(image).decode()]}],
        # Structured output: Ollama constrains generation to this JSON schema.
        "format": MealAnalysis.model_json_schema(),
        # Thinking models (gemma4, qwen3...) are much slower with reasoning on and it doesn't help much here.
        "think": False,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    try:
        # Local models can be slow, especially the first call while the model loads into memory.
        async with httpx.AsyncClient(base_url=config.OLLAMA_URL, timeout=config.OLLAMA_TIMEOUT) as client:
            r = await client.post("/api/chat", json=payload)
    except httpx.ConnectError as e:
        raise AnalysisError(f"Can't reach Ollama at {config.OLLAMA_URL}. Is it running?", 503) from e
    except httpx.TimeoutException as e:
        raise AnalysisError(f"Ollama took longer than {config.OLLAMA_TIMEOUT:.0f}s. Try again or use a smaller model.", 504) from e

    if r.status_code == 404:
        raise AnalysisError(f"Ollama has no model '{config.OLLAMA_MODEL}'. Run: ollama pull {config.OLLAMA_MODEL}", 502)
    if r.status_code != 200:
        raise AnalysisError(f"Ollama error ({r.status_code}): {r.text[:300]}", 502)

    try:
        return MealAnalysis.model_validate_json(r.json()["message"]["content"])
    except (KeyError, ValueError, ValidationError) as e:
        raise AnalysisError("The model returned a response that didn't match the expected format. Try again.") from e


async def status() -> str | None:
    """None if Ollama is reachable and has the model, otherwise a reason it isn't ready."""
    try:
        async with httpx.AsyncClient(base_url=config.OLLAMA_URL, timeout=3) as client:
            r = await client.get("/api/tags")
            r.raise_for_status()
    except httpx.HTTPError:
        return f"Can't reach Ollama at {config.OLLAMA_URL}."
    names = {m["name"] for m in r.json().get("models", [])}
    if config.OLLAMA_MODEL not in names and f"{config.OLLAMA_MODEL}:latest" not in names:
        return f"Ollama has no model '{config.OLLAMA_MODEL}'. Run: ollama pull {config.OLLAMA_MODEL}"
    return None
