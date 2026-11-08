"""Rules that build the routine frame and the rules-only plan."""
import datetime
from itertools import product

import pytest

from app.routine_rules import (BEGINNER_NOTE, Inputs, NotEnoughExercises, build_frame,
                               item_cost_sec, rules_plan, split_for, week_start)
from app.video_library import CATEGORIES, EQUIPMENT, LEVELS


def _library():
    vids, vid = [], 1
    for cat, lv, eq in product(CATEGORIES, LEVELS, EQUIPMENT):
        for n in range(3):
            vids.append({"id": vid, "youtube_id": f"v{vid:010d}", "title": f"{cat} {lv} {eq} {n}",
                         "channel": "Ch", "category": cat, "level": lv, "equipment": eq,
                         "duration_sec": 90, "active": True})
            vid += 1
    vids.append({"id": 999, "youtube_id": "inactive000", "title": "old", "channel": "Ch",
                 "category": "push", "level": "beginner", "equipment": "none",
                 "duration_sec": 90, "active": False})
    return vids


FIXTURE_LIBRARY = _library()
BY_ID = {v["id"]: v for v in FIXTURE_LIBRARY}
ALL_INPUTS = [Inputs(d, lv, eq, m) for d, lv, eq, m in
              product(range(2, 7), LEVELS, EQUIPMENT, (20, 30, 45, 60))]
GOALS = ("lose", "maintain", "gain")


def test_split_table():
    expect = {
        (2, "beginner"): ["full", "full"], (3, "beginner"): ["full"] * 3,
        (4, "beginner"): ["upper", "lower"] * 2,
        (2, "intermediate"): ["upper", "lower"], (3, "intermediate"): ["push", "pull", "legs"],
        (4, "advanced"): ["upper", "lower"] * 2,
        (5, "intermediate"): ["push", "pull", "legs", "upper", "lower"],
        (6, "advanced"): ["push", "pull", "legs"] * 2,
    }
    for (days, level), types in expect.items():
        assert split_for(days, level) == (types, None), (days, level)
    for days in (5, 6):
        assert split_for(days, "beginner") == (["upper", "lower"] * 2, BEGINNER_NOTE)
    assert BEGINNER_NOTE == ("Beginners recover better with rest days, so this plan has 4. "
                             "You can add a walk on the other days.")


def test_two_day_beginner_titles():
    frame = build_frame(Inputs(2, "beginner", "none", 30), "maintain", FIXTURE_LIBRARY)
    assert [d.title for d in frame.days] == ["Full body A", "Full body B"]


def test_frame_respects_level_and_equipment():
    for inputs, goal in product(ALL_INPUTS, GOALS):
        frame = build_frame(inputs, goal, FIXTURE_LIBRARY)
        for day in frame.days:
            vids = day.shortlist + ([day.warm_up] if day.warm_up else [])
            assert vids
            for v in vids:
                assert v["active"]
                assert LEVELS.index(v["level"]) <= LEVELS.index(inputs.level)
                assert EQUIPMENT.index(v["equipment"]) <= EQUIPMENT.index(inputs.equipment)
            assert day.warm_up["category"] == "warm_up"
            assert all(v["category"] in day.categories + ["cardio"] for v in day.shortlist)


def test_rules_plan_within_bounds():
    for inputs, goal in product(ALL_INPUTS, GOALS):
        frame = build_frame(inputs, goal, FIXTURE_LIBRARY)
        plan = rules_plan(frame)
        assert len(plan["days"]) == len(frame.days)
        for day, pd in zip(frame.days, plan["days"]):
            items = pd["items"]
            assert 2 <= len(items) <= day.max_items + 1  # + a lose finisher
            assert len(items) <= 7
            ids = [i["video_id"] for i in items]
            assert len(set(ids)) == len(ids)
            shortlist = {v["id"] for v in day.shortlist}
            assert set(ids) <= shortlist
            assert 300 + sum(item_cost_sec(i) for i in items) <= inputs.session_min * 60 * 1.1
            for i in items:
                assert 1 <= i["sets"] <= 5 and 30 <= i["rest_sec"] <= 120
                assert (i["reps"] is None) != (i["seconds"] is None)
                timed = BY_ID[i["video_id"]]["category"] in ("core", "cardio")
                assert (i["seconds"] is not None) == timed
            assert 1 <= len(pd["why"]) <= 140


def test_goal_defaults_in_rules_plan():
    for goal, (sets, reps, rest) in {"lose": (3, 12, 45), "maintain": (3, 10, 60),
                                     "gain": (4, 8, 90)}.items():
        plan = rules_plan(build_frame(Inputs(3, "intermediate", "gym", 60), goal, FIXTURE_LIBRARY))
        first = plan["days"][0]["items"][0]   # push day: first item is a push exercise
        assert (first["sets"], first["reps"], first["rest_sec"]) == (sets, reps, rest)


def test_gain_20_min_uses_three_sets():
    frame = build_frame(Inputs(3, "intermediate", "gym", 20), "gain", FIXTURE_LIBRARY)
    plan = rules_plan(frame)
    assert all(i["sets"] == 3 for d in plan["days"] for i in d["items"])
    assert all(len(d["items"]) == 2 for d in plan["days"])


def test_lose_adds_finisher_when_it_fits():
    plan = rules_plan(build_frame(Inputs(3, "beginner", "none", 45), "lose", FIXTURE_LIBRARY))
    for d in plan["days"]:
        last = d["items"][-1]
        assert BY_ID[last["video_id"]]["category"] == "cardio"
        assert (last["sets"], last["seconds"], last["rest_sec"]) == (3, 40, 45)
        assert d["why"] == "A full session with a short finisher to help fat loss."
    plan = rules_plan(build_frame(Inputs(3, "beginner", "none", 45), "maintain", FIXTURE_LIBRARY))
    assert all(BY_ID[i["video_id"]]["category"] != "cardio" for d in plan["days"] for i in d["items"])


def test_full_day_without_core_repeats_legs_or_push():
    lib = [v for v in FIXTURE_LIBRARY if v["category"] != "core"]
    plan = rules_plan(build_frame(Inputs(3, "beginner", "none", 60), "maintain", lib))
    for d in plan["days"]:
        cats = [BY_ID[i["video_id"]]["category"] for i in d["items"]]
        assert "core" not in cats and len(cats) > 3


def test_not_enough_exercises():
    lib = [v for v in FIXTURE_LIBRARY if v["category"] != "push"] + [
        {**BY_ID[1], "id": 5000, "category": "push", "level": "beginner", "equipment": "none"}]
    lib = [v for v in lib if v["category"] != "core"]
    with pytest.raises(NotEnoughExercises):
        build_frame(Inputs(3, "intermediate", "none", 30), "maintain", lib)
    with pytest.raises(NotEnoughExercises):
        build_frame(Inputs(3, "beginner", "none", 30), "maintain", [])


def test_same_type_days_rotate_videos():
    plan = rules_plan(build_frame(Inputs(6, "advanced", "gym", 30), "maintain", FIXTURE_LIBRARY))
    assert {i["video_id"] for i in plan["days"][0]["items"]} != \
        {i["video_id"] for i in plan["days"][3]["items"]}


def test_rules_plan_is_deterministic():
    frame = lambda: build_frame(Inputs(4, "intermediate", "dumbbells", 45), "lose", FIXTURE_LIBRARY)  # noqa: E731
    assert rules_plan(frame()) == rules_plan(frame())


def test_week_start_sunday_and_monday():
    assert week_start(datetime.date(2026, 11, 8)) == datetime.date(2026, 11, 2)
    assert week_start(datetime.date(2026, 11, 9)) == datetime.date(2026, 11, 9)
