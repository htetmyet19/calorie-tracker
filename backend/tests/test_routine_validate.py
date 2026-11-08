"""validate_plan: an AI plan is used only if it stays inside the frame."""
import copy

import pytest

from app.routine_rules import (Inputs, PlanInvalid, build_frame, finalize_plan, rules_plan,
                               validate_plan)
from tests.test_routine_rules import FIXTURE_LIBRARY

FRAME = build_frame(Inputs(3, "intermediate", "gym", 30), "maintain", FIXTURE_LIBRARY)
GOOD = rules_plan(FRAME)


def _bad(mutate) -> str:
    plan = copy.deepcopy(GOOD)
    mutate(plan)
    with pytest.raises(PlanInvalid) as exc:
        validate_plan(plan, FRAME)
    return exc.value.reason


def _item(plan, field, value, day=0, i=0):
    plan["days"][day]["items"][i][field] = value


def test_valid_plan_passes():
    out = validate_plan(copy.deepcopy(GOOD), FRAME)
    assert out == GOOD


def test_ai_fields_are_trimmed_to_the_frame():
    plan = copy.deepcopy(GOOD)
    plan["days"][0]["title"] = "Monster day"
    plan["days"][0]["type"] = "legs"
    plan["days"][0]["items"][0]["extra"] = "x"
    plan["days"].reverse()                    # order by index, not position
    out = validate_plan(plan, FRAME)
    assert out == GOOD


def test_rejects_not_json_object():
    for raw in ([], "x", None, {"days": "x"}, {"days": [1, 2, 3]}):
        with pytest.raises(PlanInvalid) as exc:
            validate_plan(raw, FRAME)
        assert exc.value.reason == "not_json_object"
    assert _bad(lambda p: p["days"][0].__setitem__("items", "x")) == "not_json_object"
    assert _bad(lambda p: p["days"][0]["items"].__setitem__(0, "x")) == "not_json_object"


def test_rejects_wrong_day_count():
    assert _bad(lambda p: p["days"].pop()) == "wrong_day_count"
    assert _bad(lambda p: p["days"][0].__setitem__("index", 7)) == "wrong_day_count"


def test_rejects_unknown_video():
    assert _bad(lambda p: _item(p, "video_id", 123456)) == "unknown_video"
    other_day = FRAME.days[1].shortlist[0]["id"]  # a pull video is not on the push day
    assert _bad(lambda p: _item(p, "video_id", other_day)) == "unknown_video"
    assert _bad(lambda p: _item(p, "video_id", True)) == "unknown_video"
    assert _bad(lambda p: _item(p, "video_id", str(GOOD["days"][0]["items"][0]["video_id"]))) == "unknown_video"


def test_rejects_repeat_video():
    def dup(p):
        p["days"][0]["items"][1]["video_id"] = p["days"][0]["items"][0]["video_id"]
    assert _bad(dup) == "repeat_video"


def test_rejects_item_count():
    assert _bad(lambda p: p["days"][0].__setitem__("items", p["days"][0]["items"][:1])) == "item_count"
    assert _bad(lambda p: p["days"][0].__setitem__("items", p["days"][0]["items"] * 0)) == "item_count"


def test_rejects_sets_range():
    assert _bad(lambda p: _item(p, "sets", 0)) == "sets_range"
    assert _bad(lambda p: _item(p, "sets", 6)) == "sets_range"
    assert _bad(lambda p: _item(p, "sets", 3.5)) == "sets_range"


def test_rejects_reps_range():
    assert _bad(lambda p: _item(p, "reps", 4)) == "reps_range"
    assert _bad(lambda p: _item(p, "reps", 21)) == "reps_range"


def test_rejects_seconds_range():
    def timed(value):
        def f(p):
            _item(p, "reps", None)
            _item(p, "seconds", value)
        return f
    assert _bad(timed(19)) == "seconds_range"
    assert _bad(timed(61)) == "seconds_range"


def test_rejects_rest_range():
    assert _bad(lambda p: _item(p, "rest_sec", 29)) == "rest_range"
    assert _bad(lambda p: _item(p, "rest_sec", 121)) == "rest_range"


def test_rejects_reps_or_seconds():
    assert _bad(lambda p: _item(p, "seconds", 30)) == "reps_or_seconds"   # both
    assert _bad(lambda p: _item(p, "reps", None)) == "reps_or_seconds"    # neither


def test_rejects_over_budget():
    def heavy(p):
        for it in p["days"][0]["items"]:
            it.update(sets=5, rest_sec=120, reps=10, seconds=None)
    assert _bad(heavy) == "over_budget"


def test_rejects_why_invalid():
    assert _bad(lambda p: p["days"][0].__setitem__("why", "")) == "why_invalid"
    assert _bad(lambda p: p["days"][0].__setitem__("why", "x" * 141)) == "why_invalid"
    assert _bad(lambda p: p["days"][0].__setitem__("why", "See https://example.com")) == "why_invalid"
    assert _bad(lambda p: p["days"][0].__setitem__("why", "Visit www.example.com")) == "why_invalid"
    assert _bad(lambda p: p["days"][0].__setitem__("why", 5)) == "why_invalid"


def test_finalize_adds_warm_up_and_est_min():
    plan = copy.deepcopy(GOOD)
    plan["days"][0]["items"] = [{"video_id": v["id"], "sets": 3, "reps": 10, "seconds": None,
                                 "rest_sec": 60} for v in FRAME.days[0].shortlist[:3]]
    out = finalize_plan(plan, FRAME)
    first = out["days"][0]["items"][0]
    assert first == {"video_id": FRAME.days[0].warm_up["id"], "sets": 1, "reps": None,
                     "seconds": None, "rest_sec": 0, "warm_up": True}
    assert out["days"][0]["est_min"] == round((300 + 3 * 315) / 60) == 21
    assert out["note"] is None


def test_finalize_without_warm_up_video():
    lib = [v for v in FIXTURE_LIBRARY if v["category"] != "warm_up"]
    frame = build_frame(Inputs(6, "beginner", "none", 30), "maintain", lib)
    out = finalize_plan(rules_plan(frame), frame)
    assert all(not i.get("warm_up") for d in out["days"] for i in d["items"])
    assert out["note"] == frame.note and out["note"]


def test_rejects_day_without_main_exercise():
    core = [v["id"] for v in FRAME.days[0].shortlist if v["category"] == "core"][:3]
    assert _bad(lambda p: p["days"][0].__setitem__("items", [
        {"video_id": i, "sets": 3, "reps": None, "seconds": 40, "rest_sec": 60} for i in core])) == "no_main_exercise"


def test_rejects_more_than_one_cardio():
    lose = build_frame(Inputs(3, "intermediate", "gym", 60), "lose", FIXTURE_LIBRARY)
    plan = rules_plan(lose)
    cardio = [v["id"] for v in lose.days[0].shortlist if v["category"] == "cardio"][:2]
    plan["days"][0]["items"] = plan["days"][0]["items"][:2] + [
        {"video_id": i, "sets": 3, "reps": None, "seconds": 40, "rest_sec": 45} for i in cardio]
    with pytest.raises(PlanInvalid) as exc:
        validate_plan(plan, lose)
    assert exc.value.reason == "cardio_count"
