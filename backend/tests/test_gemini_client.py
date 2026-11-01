"""Model order, per-call time limit and overall deadline of the Gemini client (no network)."""
import asyncio
import types

import pytest
from google.genai import errors

from app import config, gemini_client
from app.analysis import AnalysisError
from app.schemas import MealAnalysis

GOOD = MealAnalysis(is_food=True, items=[], notes="")


@pytest.fixture
def fake(monkeypatch):
    """Replaces the API call: behaviours[model] is a list of actions, one per attempt.
    An action is "ok", "slow" (sleeps past any limit), or an HTTP error code."""
    calls = []
    behaviours = {}

    async def fake_call(client, model, image, prompt):
        calls.append(model)
        action = behaviours[model].pop(0) if behaviours[model] else "ok"
        if action == "slow":
            await asyncio.sleep(10)
        if isinstance(action, int):
            raise errors.APIError(action, {"error": {"message": "nope", "status": "X"}})
        return types.SimpleNamespace(parsed=GOOD)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(gemini_client, "_get_client", lambda: object())
    monkeypatch.setattr(gemini_client, "_call", fake_call)
    monkeypatch.setattr(config, "GEMINI_MODEL", "main")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODELS", ["backup"])
    monkeypatch.setattr(config, "GEMINI_RETRIES", 2)
    monkeypatch.setattr(config, "GEMINI_ATTEMPT_TIMEOUT", 0.05)
    monkeypatch.setattr(config, "GEMINI_DEADLINE", 1.0)
    monkeypatch.setattr(gemini_client, "_backoff", no_sleep)
    return calls, behaviours


def run():
    return asyncio.run(gemini_client.generate(b"img", "prompt"))


def test_default_models_avoid_the_slow_latest_alias():
    # gemini-flash-latest took 49-233 s on real meal photos (Nov 2026), past Vercel's 60 s limit.
    assert "gemini-flash-latest" not in [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]
    assert config.GEMINI_DEADLINE + 10 <= 60  # room for upload and start-up inside maxDuration


def test_first_model_answers(fake):
    calls, behaviours = fake
    behaviours.update(main=["ok"], backup=[])
    assert run() == GOOD
    assert calls == ["main"]


def test_slow_model_is_cut_off_and_the_next_one_used(fake):
    calls, behaviours = fake
    behaviours.update(main=["slow"], backup=["ok"])
    assert run() == GOOD
    assert calls == ["main", "backup"]  # no retry of a model that timed out


def test_overloaded_model_is_retried_then_skipped(fake):
    calls, behaviours = fake
    behaviours.update(main=[503, 503, 503], backup=["ok"])
    assert run() == GOOD
    assert calls == ["main", "main", "main", "backup"]


def test_all_models_too_slow_gives_a_clear_timeout(fake):
    calls, behaviours = fake
    behaviours.update(main=["slow"], backup=["slow"])
    with pytest.raises(AnalysisError) as e:
        run()
    assert e.value.status_code == 504
    assert "too long" in e.value.message


def test_overall_deadline_stops_further_attempts(fake, monkeypatch):
    calls, behaviours = fake
    monkeypatch.setattr(config, "GEMINI_ATTEMPT_TIMEOUT", 5.0)
    monkeypatch.setattr(config, "GEMINI_DEADLINE", 0.1)
    behaviours.update(main=["slow"], backup=["ok"])
    with pytest.raises(AnalysisError) as e:
        run()
    assert e.value.status_code == 504
    assert calls == ["main"]  # the deadline was spent on the first model


def test_rate_limit_on_every_model_is_reported_as_429(fake):
    calls, behaviours = fake
    behaviours.update(main=[429], backup=[429])
    with pytest.raises(AnalysisError) as e:
        run()
    assert e.value.status_code == 429
