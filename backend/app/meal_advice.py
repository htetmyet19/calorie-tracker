"""Advice on a just-estimated meal: how it fits the day, with one practical tip.

The server computes every number and the verdict; the AI only words them, and
its text is checked before it is shown. Any failure falls back to a fixed
message built from the same facts. Advice is never stored.
"""
import asyncio
import logging
import re
from dataclasses import dataclass

import httpx

from . import config

log = logging.getLogger(__name__)

DEFAULT_GOAL = 2000
DEFAULT_GOAL_TYPE = "maintain"
USES_MOST = 0.8


@dataclass
class Facts:
    items: list[dict]
    eaten: bool
    meal_kcal: int
    eaten_before: int
    goal: int
    goal_type: str
    left_before: int
    left_after: int
    over_by: int
    biggest: str
    half_saves: int
    protein_g: int
    verdict: str


def meal_facts(items: list[dict], eaten: bool, eaten_today_kcal: float,
               goal_kcal: int | None, goal_type: str | None) -> Facts:
    meal = round(sum(i["calories"] for i in items))
    before = round(eaten_today_kcal)
    goal = goal_kcal or DEFAULT_GOAL
    left_before = goal - before
    left_after = left_before - meal
    big = max(items, key=lambda i: i["calories"]) if items else None  # max keeps the first on ties
    if left_after < 0:
        verdict = "goes_over"
    elif left_before > 0 and meal > USES_MOST * left_before:
        verdict = "uses_most"
    else:
        verdict = "fits_well"
    return Facts(
        items=items, eaten=eaten, meal_kcal=meal, eaten_before=before, goal=goal,
        goal_type=goal_type or DEFAULT_GOAL_TYPE, left_before=left_before, left_after=left_after,
        over_by=max(0, -left_after), biggest=big["name"] if big else "",
        half_saves=round(big["calories"] / 2) if big else 0,
        protein_g=round(sum(i.get("protein_g", 0) for i in items)), verdict=verdict)


# ---- checking what the AI wrote ----

MAX_CHARS = 320
BLOCKED = (
    r"\bdon'?t eat", r"\bdo not eat", r"\bskip(s|ped|ping)?\b", r"\bavoid eating",
    r"\bstarv\w*", r"\bfast\b", r"\bfasting\b", r"\bburn (it|this|that) off\b", r"\bguilt\w*",
    r"\bbad food", r"\bcheat\w*", r"\bpunish\w*", r"\bpurg(e|es|ed|ing)\b", r"\bthrow up\b",
    r"\bashamed\b", r"\bshame\w*",
)
_BLOCKED = re.compile("|".join(BLOCKED), re.IGNORECASE)
_KCAL = re.compile(r"(\d[\d,]*)\s*(?:kcal|calories)\b", re.IGNORECASE)


class AdviceRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _allowed_numbers(f: Facts) -> list[int]:
    return [f.meal_kcal, f.eaten_before, f.eaten_before + f.meal_kcal, f.goal, abs(f.left_before),
            abs(f.left_after), f.over_by, f.half_saves, *(round(i["calories"]) for i in f.items)]


def _near(n: int, target: int) -> bool:
    return abs(n - target) <= max(10, 0.03 * target)


def check_advice(text: str, facts: Facts) -> str:
    """The stripped text if it is safe to show, else AdviceRejected naming the first broken rule."""
    text = (text or "").strip()
    plain = text.replace("\u2019", "'")   # curly apostrophes: "don’t eat"
    low = plain.lower()
    if not text:
        raise AdviceRejected("empty")
    if len(text) > MAX_CHARS:
        raise AdviceRejected("too_long")
    if "http" in low or "www." in low or ".com" in low:
        raise AdviceRejected("link")
    if _BLOCKED.search(plain):
        raise AdviceRejected("blocked")
    allowed = _allowed_numbers(facts)
    for m in _KCAL.finditer(plain):
        n = int(m.group(1).replace(",", ""))
        if not any(_near(n, t) for t in allowed):
            raise AdviceRejected("wrong_number")
    return text


# ---- the fixed message, used whenever the AI's text can't be ----

def _fallback(f: Facts, food: str) -> str:
    n = lambda v: f"{v:,}"  # noqa: E731
    meal, goal = n(f.meal_kcal), n(f.goal)
    if f.verdict == "fits_well":
        return f"About {meal} kcal. That leaves {n(f.left_after)} kcal of your {goal} kcal goal today."
    if f.verdict == "uses_most":
        if f.eaten:
            return (f"About {meal} kcal, most of the {n(f.left_before)} kcal you had left today. "
                    "A lighter next meal will keep you on track.")
        return (f"About {meal} kcal, most of the {n(f.left_before)} kcal you have left today. "
                f"A smaller portion of {food} would leave more room for later.")
    if f.goal_type == "gain":
        return (f"About {meal} kcal, which puts today {n(f.over_by)} kcal above your {goal} kcal goal. "
                "That's fine while you're building.")
    if f.eaten:
        return (f"About {meal} kcal, which puts today {n(f.over_by)} kcal over your {goal} kcal goal. "
                "One day over is fine; tomorrow is a fresh start.")
    return (f"About {meal} kcal, which would put today {n(f.over_by)} kcal over your {goal} kcal goal. "
            f"A smaller portion of {food} saves about {n(f.half_saves)} kcal.")


def fallback_text(facts: Facts) -> str:
    """Spec §4.4. Food names are typed by the client, so if one trips the checks it is left out."""
    text = _fallback(facts, f"the {facts.biggest}")
    try:
        return check_advice(text, facts)
    except AdviceRejected:
        return _fallback(facts, "the largest item")


# ---- asking the AI ----

ADVICE_TIMEOUT_SEC = 10

PROMPT = """You are a supportive nutrition coach in a calorie-tracking app. Write a short note
about one meal, using ONLY the facts below. The numbers are already worked out: use them as given.

Facts:
- Meal: {items}
- Meal total: {meal} kcal
- Eaten earlier today: {before} kcal
- Daily goal: {goal} kcal (goal type: {goal_type})
- Left before this meal: {left_before} kcal; left after it: {left_after} kcal; over the goal by: {over} kcal
- Largest item: {biggest}; half of it is about {half} kcal
- Protein in this meal: {protein} g
- Verdict: {verdict} (fits_well = fits comfortably, uses_most = uses most of what is left,
  goes_over = puts today over the goal{gain_note})
- {timing}

Write 1 to 3 short sentences in plain, warm language, at most {max_chars} characters:
say how the meal fits today, then give at most ONE practical tip: {tip_kind}
Rules: never tell the person not to eat, to skip food or meals, or to fast. No guilt, shame
or judging words. No medical, health or weight-loss claims, no "burn it off". No links.
Only use the numbers above. Reply with the note only, as plain text."""


def build_prompt(f: Facts) -> str:
    n = lambda v: f"{v:,}"  # noqa: E731
    items = "; ".join(f"{i['name']} ({round(i['calories']):,} kcal)" for i in f.items)
    if f.eaten:
        timing = "The person has ALREADY EATEN this meal, so the tip is about the rest of today."
        tip = "a lighter next meal, more protein later, or water. Do not suggest changing this meal."
    else:
        timing = "The person has NOT EATEN this meal yet, so the tip is about this plate."
        tip = "a smaller portion of one item, a swap, or adding protein."
    return PROMPT.format(
        items=items, meal=n(f.meal_kcal), before=n(f.eaten_before), goal=n(f.goal), goal_type=f.goal_type,
        left_before=n(f.left_before), left_after=n(f.left_after), over=n(f.over_by), biggest=f.biggest,
        half=n(f.half_saves), protein=f.protein_g, verdict=f.verdict, timing=timing, tip_kind=tip,
        max_chars=MAX_CHARS,
        gain_note="; for a gain goal going over a little is fine" if f.goal_type == "gain" else "")


async def _ask_gemini(prompt: str) -> str:
    from google.genai import errors, types

    from .gemini_client import _get_client, _models
    client = _get_client()
    last: Exception | None = None
    for model in _models():
        try:
            resp = await client.aio.models.generate_content(
                model=model, contents=[prompt],
                config=types.GenerateContentConfig(response_mime_type="text/plain", temperature=0.5))
            return resp.text or ""
        except errors.APIError as e:  # overloaded, out of quota, retired: try the next model
            last = e
    raise RuntimeError(f"all Gemini models failed ({type(last).__name__})")


async def _ask_ollama(prompt: str) -> str:
    payload = {"model": config.OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}],
               "think": False, "stream": False, "options": {"temperature": 0.5}}
    async with httpx.AsyncClient(base_url=config.OLLAMA_URL, timeout=ADVICE_TIMEOUT_SEC) as client:
        r = await client.post("/api/chat", json=payload)
    r.raise_for_status()
    return r.json()["message"]["content"]


async def ask_model(prompt: str) -> str:
    if config.LLM_PROVIDER == "gemini":
        return await _ask_gemini(prompt)
    return await _ask_ollama(prompt)


async def get_advice(facts: Facts, allow_ai: bool = True) -> tuple[str, str, str | None]:
    """(text, source, reason): checked AI text, or the fixed message and why."""
    reason = None if allow_ai else "limit"
    if allow_ai:
        try:
            raw = await asyncio.wait_for(ask_model(build_prompt(facts)), ADVICE_TIMEOUT_SEC)
            text = check_advice(raw if isinstance(raw, str) else "", facts)
            log.warning("meal_advice source=ai reason=None")  # WARNING: the app sets no log level
            return text, "ai", None
        except asyncio.TimeoutError:
            reason = "timeout"
        except AdviceRejected as e:
            reason = e.reason
        except Exception:  # any provider failure: the client still gets advice
            reason = "provider_error"
    log.warning("meal_advice source=rules reason=%s", reason)
    return fallback_text(facts), "rules", reason
