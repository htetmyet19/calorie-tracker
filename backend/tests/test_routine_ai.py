"""The AI fills the frame; any failure means the rules-only plan."""
import asyncio
import copy
import json
import logging
import re

import pytest

from app import routine_ai
from app.routine_rules import Inputs, build_frame, rules_plan
from tests.test_routine_rules import FIXTURE_LIBRARY

FRAME = build_frame(Inputs(3, "intermediate", "gym", 30), "lose", FIXTURE_LIBRARY)
RULES = rules_plan(FRAME)


def _run(monkeypatch, reply=None, exc=None, delay=0.0):
    async def fake(prompt):
        if delay:
            await asyncio.sleep(delay)
        if exc:
            raise exc
        return reply
    monkeypatch.setattr(routine_ai, "ask_model", fake)
    return asyncio.run(routine_ai.build_plan(FRAME))


def test_valid_ai_plan_is_used(monkeypatch):
    ai = copy.deepcopy(RULES)
    for d in ai["days"]:
        d["why"] = "Picked for you."
        for it in d["items"]:
            it["sets"] = 2
    plan, source, reason = _run(monkeypatch, json.dumps(ai))
    assert source == "ai" and reason is None
    assert plan["days"][0]["why"] == "Picked for you."
    assert all(it["sets"] == 2 for d in plan["days"] for it in d["items"])


def test_invalid_ai_plan_falls_back(monkeypatch, caplog):
    ai = copy.deepcopy(RULES)
    ai["days"][0]["items"][0]["video_id"] = 123456
    with caplog.at_level(logging.WARNING):
        assert _run(monkeypatch, json.dumps(ai)) == (RULES, "rules", "unknown_video")
    assert "routine_ai_fallback reason=unknown_video" in caplog.text


def test_not_json_falls_back(monkeypatch):
    assert _run(monkeypatch, "Sure! Here is your plan:") == (RULES, "rules", "not_json")


def test_provider_error_falls_back(monkeypatch):
    assert _run(monkeypatch, exc=RuntimeError("quota")) == (RULES, "rules", "provider_error")


def test_timeout_falls_back(monkeypatch):
    monkeypatch.setattr(routine_ai, "AI_TIMEOUT_SEC", 0.01)
    assert _run(monkeypatch, "{}", delay=1) == (RULES, "rules", "timeout")


def test_prompt_lists_only_shortlist_ids():
    prompt = routine_ai.build_prompt(FRAME)
    allowed = {v["id"] for d in FRAME.days for v in d.shortlist}
    listed = {int(m) for m in re.findall(r"^\s*(\d+) \|", prompt, re.M)}
    assert listed and listed <= allowed
    assert "lose" in prompt and "intermediate" in prompt and "30" in prompt
    for d in FRAME.days:
        assert f"Day {d.index}" in prompt and str(d.max_items) in prompt
    assert not re.search(r"injur", prompt, re.I)  # the injury answer never reaches the server


def test_prompt_and_reply_never_logged(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        _run(monkeypatch, "not json SECRET-REPLY")
    assert "SECRET-REPLY" not in caplog.text and "Day 0" not in caplog.text


@pytest.mark.parametrize("provider", ["gemini", "ollama"])
def test_ask_model_dispatches_on_provider(monkeypatch, provider):
    called = []

    async def fake_gemini(prompt):
        called.append("gemini")
        return "{}"

    async def fake_ollama(prompt):
        called.append("ollama")
        return "{}"
    monkeypatch.setattr(routine_ai.config, "LLM_PROVIDER", provider)
    monkeypatch.setattr(routine_ai, "_ask_gemini", fake_gemini)
    monkeypatch.setattr(routine_ai, "_ask_ollama", fake_ollama)
    assert asyncio.run(routine_ai.ask_model("p")) == "{}"
    assert called == [provider]


def test_lose_prompt_counts_the_finisher_within_seven():
    frame = build_frame(Inputs(3, "intermediate", "gym", 60), "lose", FIXTURE_LIBRARY)
    prompt = routine_ai.build_prompt(frame)
    assert frame.days[0].max_items == 7
    assert "at most 6 exercises plus one cardio finisher" in prompt
    assert "at most 7 exercises plus" not in prompt


def test_validation_bugs_are_not_blamed_on_the_provider(monkeypatch):
    def boom(raw, frame):
        raise KeyError("x")
    monkeypatch.setattr(routine_ai, "validate_plan", boom)
    assert _run(monkeypatch, "{}")[2] == "invalid_shape"


def test_null_reply_is_not_json(monkeypatch):
    assert _run(monkeypatch, None)[2] == "not_json"
