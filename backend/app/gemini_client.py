"""Sends a meal photo to Gemini and gets back structured nutrition estimates."""
import asyncio
import logging

from google import genai
from google.genai import errors, types

from . import config
from .analysis import AnalysisError
from .schemas import MealAnalysis

log = logging.getLogger(__name__)

# 503 = model overloaded, 500/504 = transient server errors: worth retrying, then trying another model.
_TRANSIENT = {500, 503, 504}
# 429 = quota for this model used up; quotas are per model, so another model may still work.
_TRY_NEXT_MODEL = _TRANSIENT | {429}
# Don't start an attempt with less time than this left. asyncio may fire a timer up to one clock
# tick early (about 15.6 ms on Windows), so the deadline can look "not quite reached" right after
# it passed, and no model answers in a few milliseconds anyway.
_MIN_ATTEMPT_SECONDS = 0.05

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if not config.GEMINI_API_KEY:
        raise AnalysisError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.", 500)
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _models() -> list[str]:
    """Primary model first, then fallbacks, without duplicates."""
    return list(dict.fromkeys([config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]))


async def _call(client: genai.Client, model: str, image: bytes, prompt: str):
    return await client.aio.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=image, mime_type="image/jpeg"), prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MealAnalysis,
            temperature=0.2,
        ),
    )


async def _backoff(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def generate(image: bytes, prompt: str) -> MealAnalysis:
    client = _get_client()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + config.GEMINI_DEADLINE
    last_error: errors.APIError | None = None
    timed_out = False

    for model in _models():
        for attempt in range(config.GEMINI_RETRIES + 1):
            remaining = deadline - loop.time()
            if remaining <= _MIN_ATTEMPT_SECONDS:
                timed_out = True
                break
            try:
                response = await asyncio.wait_for(
                    _call(client, model, image, prompt), min(config.GEMINI_ATTEMPT_TIMEOUT, remaining)
                )
            except asyncio.TimeoutError:  # the builtin TimeoutError only from Python 3.11
                # A slow model rarely gets faster on a retry: go straight to the next one.
                timed_out = True
                log.warning("Gemini %s attempt %d timed out", model, attempt + 1)
                break
            except errors.APIError as e:
                last_error = e
                log.warning("Gemini %s attempt %d failed (%s): %s", model, attempt + 1, e.code, e.message)
                if e.code in _TRANSIENT and attempt < config.GEMINI_RETRIES:
                    await _backoff(2**attempt)  # 1s, 2s, ...
                    continue
                if e.code in _TRY_NEXT_MODEL or e.code == 404:  # 404: model retired for this key
                    break
                raise AnalysisError(f"Gemini rejected the request ({e.code}): {e.message}", 502) from e

            analysis = response.parsed
            if not isinstance(analysis, MealAnalysis):
                raise AnalysisError("Gemini returned a response that didn't match the expected format. Try again.")
            return analysis
        if deadline - loop.time() <= _MIN_ATTEMPT_SECONDS:
            timed_out = True
            break

    if last_error is not None and last_error.code == 429 and not timed_out:
        raise AnalysisError("Gemini free-tier rate limit reached on all models. Wait a minute and try again.", 429)
    if timed_out:
        raise AnalysisError("The estimate is taking too long right now. Please try again in a minute.", 504)
    raise AnalysisError(
        f"Gemini is unavailable right now (tried {', '.join(_models())}). Please try again shortly.", 503
    )
