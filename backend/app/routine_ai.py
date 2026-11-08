"""The AI step of a workout routine: fill the rules' frame, or fall back to rules.

The model only sees the frame (inputs, goal, per-day shortlists) and must pick
from those ids. Its answer is checked by routine_rules.validate_plan; any
error, timeout or broken rule means the rules-only plan is used instead.
Neither the prompt nor the reply is logged.
"""
import asyncio
import json
import logging

import httpx

from . import config
from .routine_rules import (MAX_ITEMS, MIN_ITEMS, WORK_SEC, Frame, PlanInvalid, rules_plan,
                            validate_plan)

log = logging.getLogger(__name__)

AI_TIMEOUT_SEC = 20

PROMPT_HEAD = """You are a fitness coach writing one week of workouts. You may ONLY use
exercises from each day's list below, by their id. Never invent exercises.

Client: goal {goal}, level {level}, equipment {equipment}, {minutes} minutes per session.
A 5-minute warm-up is added automatically; do not include one.

Rules for every day:
- {min_items} to {max_total} exercises, each id used at most once per day.
- Each exercise has sets 1-5, rest_sec 30-120, and EITHER reps 5-20 OR seconds 20-60
  (use seconds for core and cardio, reps otherwise; set the other to null).
- Time per exercise = sets x ((seconds, or {work} if using reps) + rest_sec).
  The day's exercises must fit its time budget.
- Suit the goal: lose = higher reps, short rest, a cardio finisher if it fits;
  maintain = moderate; gain = fewer reps, more sets, longer rest.
- "why": one plain sentence (max 140 characters) on why this day suits the client.
  No links, no medical claims.

Reply with JSON only, exactly this shape:
{{"days":[{{"index":0,"why":"...","items":[{{"video_id":1,"sets":3,"reps":10,"seconds":null,"rest_sec":60}}]}}]}}
"""


def build_prompt(frame: Frame) -> str:
    inp = frame.inputs
    parts = [PROMPT_HEAD.format(
        goal=frame.goal, level=inp.level, equipment=inp.equipment, minutes=inp.session_min,
        min_items=MIN_ITEMS, max_total=MAX_ITEMS, work=WORK_SEC)]
    lose = frame.goal == "lose"
    for day in frame.days:
        # The finisher counts toward the 7-item limit, so lose days leave room for it.
        cap = min(day.max_items, MAX_ITEMS - 1) if lose else day.max_items
        parts.append(f"Day {day.index} ({day.title}): at most {cap} exercises"
                     f"{' plus one cardio finisher' if lose else ''}, "
                     f"time budget {day.budget_sec} seconds. Exercises (id | title | category):")
        parts += [f"  {v['id']} | {v['title']} | {v['category']}" for v in day.shortlist]
    return "\n".join(parts)


async def _ask_gemini(prompt: str) -> str:
    from google.genai import errors, types

    from .gemini_client import _get_client, _models
    client = _get_client()
    last: Exception | None = None
    for model in _models():
        try:
            resp = await client.aio.models.generate_content(
                model=model, contents=[prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json",
                                                   temperature=0.4))
            return resp.text or ""
        except errors.APIError as e:  # overloaded, out of quota, retired: try the next model
            last = e
    raise RuntimeError(f"all Gemini models failed ({type(last).__name__})")


async def _ask_ollama(prompt: str) -> str:
    payload = {"model": config.OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}],
               "format": "json", "think": False, "stream": False, "options": {"temperature": 0.4}}
    async with httpx.AsyncClient(base_url=config.OLLAMA_URL, timeout=AI_TIMEOUT_SEC) as client:
        r = await client.post("/api/chat", json=payload)
    r.raise_for_status()
    return r.json()["message"]["content"]


async def ask_model(prompt: str) -> str:
    if config.LLM_PROVIDER == "gemini":
        return await _ask_gemini(prompt)
    return await _ask_ollama(prompt)


async def build_plan(frame: Frame) -> tuple[dict, str, str | None]:
    """(plan, source, fallback_reason): the AI's plan if it passes every check, else rules."""
    try:
        raw = await asyncio.wait_for(ask_model(build_prompt(frame)), AI_TIMEOUT_SEC)
        plan = validate_plan(json.loads(raw), frame)
        return plan, "ai", None
    except asyncio.TimeoutError:
        reason = "timeout"
    except json.JSONDecodeError:
        reason = "not_json"
    except PlanInvalid as e:
        reason = e.reason
    except Exception:  # any provider failure: the client still gets a routine
        reason = "provider_error"
    log.warning("routine_ai_fallback reason=%s", reason)
    return rules_plan(frame), "rules", reason

