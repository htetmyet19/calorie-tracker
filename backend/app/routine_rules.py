"""Workout routines: the rules that make every routine safe.

Rules decide the split, which videos a client may get, and the time budget
(the frame). The AI only picks and orders inside that frame, and anything it
returns is checked here before use. rules_plan() is both the fallback and the
baseline the AI is compared against. Everything here is pure.
"""
import datetime
from dataclasses import dataclass

from .video_library import usable

WARM_UP_SEC = 300
WORK_SEC = 45            # assumed time for one set done by reps
TIMED_SEC = 40           # core and cardio sets are done for time
TIMED = ("core", "cardio")
MIN_ITEMS, MAX_ITEMS = 2, 7
PER_CATEGORY_CAP = 8     # shortlist size per category, keeps the AI prompt small

BEGINNER_NOTE = ("Beginners recover better with rest days, so this plan has 4. "
                 "You can add a walk on the other days.")

SPLITS = {
    "beginner": {2: ["full", "full"], 3: ["full"] * 3, 4: ["upper", "lower"] * 2},
    "other": {2: ["upper", "lower"], 3: ["push", "pull", "legs"], 4: ["upper", "lower"] * 2,
              5: ["push", "pull", "legs", "upper", "lower"], 6: ["push", "pull", "legs"] * 2},
}
DAY_CATEGORIES = {
    "full": ["legs", "push", "pull", "core"], "upper": ["push", "pull", "core"],
    "lower": ["legs", "core"], "push": ["push", "core"], "pull": ["pull", "core"],
    "legs": ["legs", "core"],
}
TITLES = {"full": "Full body", "upper": "Upper body", "lower": "Lower body",
          "push": "Push", "pull": "Pull", "legs": "Legs"}
GOAL_DEFAULTS = {"lose": (3, 12, 45), "maintain": (3, 10, 60), "gain": (4, 8, 90)}
FINISHER = {"sets": 3, "reps": None, "seconds": TIMED_SEC, "rest_sec": 45}
WHY = {
    "lose_finisher": "A full session with a short finisher to help fat loss.",
    "lose": "Steady strength work to keep you moving toward your goal.",
    "maintain": "Balanced strength work to keep what you've built.",
    "gain": "Heavier sets with longer rest to build muscle.",
}


class NotEnoughExercises(Exception):
    """The library can't fill a day for these inputs."""


@dataclass
class Inputs:
    days_per_week: int
    level: str
    equipment: str
    session_min: int


@dataclass
class Day:
    index: int
    type: str
    title: str
    categories: list[str]
    warm_up: dict | None
    shortlist: list[dict]
    max_items: int
    budget_sec: int


@dataclass
class Frame:
    inputs: Inputs
    goal: str
    days: list[Day]
    note: str | None
    defaults: dict  # the goal's prescription, after the 20-minute gain adjustment


def split_for(days: int, level: str) -> tuple[list[str], str | None]:
    if level == "beginner":
        if days >= 5:
            return list(SPLITS["beginner"][4]), BEGINNER_NOTE
        return list(SPLITS["beginner"][days]), None
    return list(SPLITS["other"][days]), None


def goal_defaults(goal: str) -> dict:
    sets, reps, rest = GOAL_DEFAULTS[goal]
    return {"sets": sets, "reps": reps, "seconds": None, "rest_sec": rest}


def item_cost_sec(item: dict) -> int:
    return item["sets"] * ((item["seconds"] or WORK_SEC) + item["rest_sec"])


def week_start(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def _titles(types: list[str]) -> list[str]:
    if types == ["full", "full"]:
        return ["Full body A", "Full body B"]
    return [TITLES[t] for t in types]


def build_frame(inputs: Inputs, goal: str, videos: list[dict]) -> Frame:
    types, note = split_for(inputs.days_per_week, inputs.level)
    budget = (inputs.session_min * 60) - WARM_UP_SEC
    defaults = goal_defaults(goal)
    if MIN_ITEMS * item_cost_sec(defaults) > budget:
        defaults["sets"] = 3  # gain at 20 min: 4 sets × 2 exercises don't fit
    max_items = max(MIN_ITEMS, min(MAX_ITEMS, budget // item_cost_sec(defaults)))

    pool = sorted((v for v in videos if v.get("active", True)
                   and usable(v, inputs.level, inputs.equipment)), key=lambda v: v["id"])
    warm_ups = [v for v in pool if v["category"] == "warm_up"]
    used_warm_ups: set[int] = set()

    days = []
    for i, (t, title) in enumerate(zip(types, _titles(types))):
        cats = list(DAY_CATEGORIES[t])
        shortlist = []
        for c in cats + (["cardio"] if goal == "lose" else []):
            shortlist += [v for v in pool if v["category"] == c][:PER_CATEGORY_CAP]
        if sum(1 for v in shortlist if v["category"] in cats) < MIN_ITEMS:
            raise NotEnoughExercises(t)
        fresh = [v for v in warm_ups if v["id"] not in used_warm_ups]
        warm_up = (fresh or warm_ups or [None])[0]
        if warm_up:
            used_warm_ups.add(warm_up["id"])
        days.append(Day(i, t, title, cats, warm_up, shortlist, max_items, budget))
    return Frame(inputs, goal, days, note, defaults)


def _item(video: dict, defaults: dict) -> dict:
    if video["category"] in TIMED:
        return {"video_id": video["id"], "sets": defaults["sets"], "reps": None,
                "seconds": TIMED_SEC, "rest_sec": defaults["rest_sec"]}
    return {"video_id": video["id"], **defaults}


def rules_plan(frame: Frame) -> dict:
    """Deterministic plan from the frame: the fallback and the baseline."""
    used_by_type: dict[str, set[int]] = {}
    days = []
    for day in frame.days:
        seen_type = used_by_type.setdefault(day.type, set())
        by_cat = {c: [v for v in day.shortlist if v["category"] == c] for c in day.categories}
        items, spent, in_day = [], 0, set()
        cap, budget = day.max_items, day.budget_sec
        has_cardio = any(v["category"] == "cardio" for v in day.shortlist)
        if frame.goal == "lose" and has_cardio:
            # Keep room for the finisher, as long as two main exercises still fit.
            reserve = item_cost_sec(FINISHER)
            if MIN_ITEMS * item_cost_sec(frame.defaults) <= budget - reserve:
                cap, budget = min(cap, MAX_ITEMS - 1), budget - reserve
        while len(items) < cap:
            added = False
            for c in day.categories:
                if len(items) >= cap:
                    break
                options = [v for v in by_cat[c] if v["id"] not in in_day]
                if not options:
                    continue
                pick = next((v for v in options if v["id"] not in seen_type), options[0])
                item = _item(pick, frame.defaults)
                if spent + item_cost_sec(item) > budget:
                    continue
                items.append(item)
                spent += item_cost_sec(item)
                in_day.add(pick["id"])
                added = True
            if not added:
                break
        if len(items) < 2:
            raise NotEnoughExercises(day.type)
        why = WHY[frame.goal]
        if frame.goal == "lose":
            cardio = [v for v in day.shortlist if v["category"] == "cardio" and v["id"] not in in_day]
            if (cardio and len(items) < MAX_ITEMS
                    and spent + item_cost_sec(FINISHER) <= day.budget_sec):
                pick = next((v for v in cardio if v["id"] not in seen_type), cardio[0])
                items.append({"video_id": pick["id"], **FINISHER})
                in_day.add(pick["id"])
                why = WHY["lose_finisher"]
        seen_type |= in_day
        days.append({"index": day.index, "type": day.type, "title": day.title,
                     "why": why, "items": items})
    return {"days": days}
