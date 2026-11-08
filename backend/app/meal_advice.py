"""Advice on a just-estimated meal: how it fits the day, with one practical tip.

The server computes every number and the verdict; the AI only words them, and
its text is checked before it is shown. Any failure falls back to a fixed
message built from the same facts. Advice is never stored.
"""
import re
from dataclasses import dataclass

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
