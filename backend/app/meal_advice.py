"""Advice on a just-estimated meal: how it fits the day, with one practical tip.

The server computes every number and the verdict; the AI only words them, and
its text is checked before it is shown. Any failure falls back to a fixed
message built from the same facts. Advice is never stored.
"""
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
