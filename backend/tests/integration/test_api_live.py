"""The API end to end: real Supabase tokens through auth, Store and RLS."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration

ITEM = {"name": "dal", "portion": "1 bowl", "grams": 200, "calories": 150,
        "protein_g": 8, "carbs_g": 20, "fat_g": 3, "confidence": "high"}
MEAL = {"eaten_at": "2026-10-31T08:00", "meal_type": "breakfast", "items": [ITEM]}


@pytest.fixture
def api():
    with TestClient(app) as c:
        yield c


def auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


def test_new_user_chooses_role_then_logs_a_meal(api, make_user):
    u = auth(make_user(role=None))
    r = api.get("/api/me", headers=u)
    assert (r.status_code, r.json()) == (404, {"detail": "no_profile"})

    r = api.post("/api/me/role", headers=u, json={"role": "client", "display_name": "Asha"})
    assert r.status_code == 201
    assert (r.json()["role"], r.json()["display_name"]) == ("client", "Asha")

    r = api.post("/api/meals", headers=u, json=MEAL)
    assert r.status_code == 201
    meal_id = r.json()["id"]

    r = api.get("/api/meals", headers=u, params={"date": "2026-10-31"})
    assert r.status_code == 200
    assert [m["id"] for m in r.json()["meals"]] == [meal_id]
    assert r.json()["total_calories"] == 150


def test_other_user_sees_none_of_my_meals(api, make_user):
    me, other = auth(make_user()), auth(make_user())
    assert api.post("/api/meals", headers=me, json=MEAL).status_code == 201
    r = api.get("/api/meals", headers=other, params={"date": "2026-10-31"})
    assert r.status_code == 200
    assert r.json()["meals"] == []


def test_missing_token_is_401(api):
    r = api.get("/api/meals", params={"date": "2026-10-31"})
    assert (r.status_code, r.json()) == (401, {"detail": "not_logged_in"})


def test_user_without_profile_must_choose_role(api, make_user):
    r = api.get("/api/meals", headers=auth(make_user(role=None)), params={"date": "2026-10-31"})
    assert (r.status_code, r.json()) == (409, {"detail": "choose_role"})


def test_settings_move_after_weight_log_then_conflict(api, make_user):
    # Ruling R7 end to end: weight logged first, browser move succeeds, second move 409.
    u = auth(make_user())
    assert api.put("/api/weights/2026-10-31", headers=u, json={"weight_kg": 70}).status_code == 200
    r = api.put("/api/settings?only_if_empty=1", headers=u,
                json={"height_cm": 170, "age": 30, "sex": "male", "activity": 1.55,
                      "weight_goal": "maintain", "goal_kcal": 2500})
    assert r.status_code == 200
    assert r.json()["goal_kcal"] == 2500 and r.json()["weight_kg"] == 70
    r = api.put("/api/settings?only_if_empty=true", headers=u, json={"goal_kcal": 1500})
    assert r.status_code == 409 and r.json() == {"detail": "settings_exist"}
    assert api.get("/api/settings", headers=u).json()["goal_kcal"] == 2500


def test_meals_report_photo_removed(api, make_user, service):
    u = make_user()
    mid = api.post("/api/meals", headers=auth(u), json=MEAL).json()["id"]
    day = api.get("/api/meals", headers=auth(u), params={"date": "2026-10-31"}).json()
    assert day["meals"][0]["photo_removed"] is False and day["meals"][0]["has_photo"] is False
    service.patch("/meals", params={"id": f"eq.{mid}"}, json={"photo_removed": True})
    day = api.get("/api/meals", headers=auth(u), params={"date": "2026-10-31"}).json()
    assert day["meals"][0]["photo_removed"] is True


def test_daily_totals_sum_my_meals_only(api, make_user):
    me, other = auth(make_user()), auth(make_user())
    for when, kcal in (("2026-10-29T08:00", 150), ("2026-10-29T19:00", 150), ("2026-10-31T23:30", 150)):
        meal = {**MEAL, "eaten_at": when, "items": [{**ITEM, "calories": kcal}]}
        assert api.post("/api/meals", headers=me, json=meal).status_code == 201
    assert api.post("/api/meals", headers=other, json=MEAL).status_code == 201

    r = api.get("/api/meals/daily-totals", headers=me, params={"from": "2026-10-28", "to": "2026-10-31"})
    assert r.status_code == 200
    assert r.json() == [
        {"date": "2026-10-28", "total_calories": 0.0},
        {"date": "2026-10-29", "total_calories": 300.0},
        {"date": "2026-10-30", "total_calories": 0.0},
        {"date": "2026-10-31", "total_calories": 150.0},
    ]
    r = api.get("/api/meals/daily-totals", headers=other, params={"from": "2026-10-31", "to": "2026-10-31"})
    assert r.json() == [{"date": "2026-10-31", "total_calories": 150.0}]


def _seed_videos(service):
    """Enough beginner/no-equipment videos for a 3-day full-body routine."""
    import uuid
    for cat in ("warm_up", "legs", "push", "pull", "core"):
        for n in range(2):
            r = service.post("/exercise_videos", json={
                "youtube_id": uuid.uuid4().hex[:11], "title": f"{cat} {n}", "channel": "Ch",
                "category": cat, "level": "beginner", "equipment": "none", "duration_sec": 60})
            assert r.status_code == 201, r.text


def test_routine_round_trip(api, make_user, service, monkeypatch):
    from app import routine_ai

    async def no_ai(prompt):
        raise RuntimeError("no AI in tests")
    monkeypatch.setattr(routine_ai, "ask_model", no_ai)
    _seed_videos(service)
    me, other = auth(make_user()), auth(make_user())
    body = {"days_per_week": 3, "level": "beginner", "equipment": "none", "session_min": 30}
    r = api.post("/api/routines", headers=me, json=body)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["source"] == "rules"

    r = api.put(f"/api/routines/{rid}/days/0/done/2026-11-09", headers=me)
    assert r.status_code == 204
    assert api.put(f"/api/routines/{rid}/days/0/done/2026-11-09", headers=me).status_code == 204
    r = api.get("/api/routines/active", headers=me, params={"today": "2026-11-11"})
    assert r.json()["routine"]["id"] == rid
    assert r.json()["done"] == [{"day_index": 0, "done_on": "2026-11-09"}]

    # Another user can neither see nor tick it.
    r = api.get("/api/routines/active", headers=other, params={"today": "2026-11-11"})
    assert r.json()["routine"] is None
    assert api.put(f"/api/routines/{rid}/days/0/done/2026-11-09", headers=other).status_code == 404

    assert api.delete(f"/api/routines/{rid}/days/0/done/2026-11-09", headers=me).status_code == 204
    r = api.get("/api/routines/active", headers=me, params={"today": "2026-11-11"})
    assert r.json()["done"] == []
