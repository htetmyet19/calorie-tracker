"""RLS for the workout tables: shared read-only library, owner-only routines and ticks."""
import uuid

import httpx

import pytest

pytestmark = pytest.mark.integration

REP = {"Prefer": "return=representation"}


def _video(service, **over) -> dict:
    row = {"youtube_id": uuid.uuid4().hex[:11], "title": "Push-up", "channel": "Ch",
           "category": "push", "level": "beginner", "equipment": "none", "duration_sec": 90}
    row.update(over)
    r = service.post("/exercise_videos", json=row)
    assert r.status_code == 201, r.text
    return r.json()[0]


def _routine(rest, user, active=True) -> httpx.Response:
    return rest(user.token).post("/routines", headers=REP, json={
        "user_id": user.id, "days_per_week": 3, "level": "beginner", "equipment": "none",
        "session_min": 30, "goal": "maintain", "source": "rules", "plan": {"days": []},
        "active": active})


def test_videos_readable_not_writable(make_user, rest, service):
    a = make_user("client")
    v = _video(service)
    hidden = _video(service, active=False)
    r = rest(a.token).get("/exercise_videos", params={"id": f"in.({v['id']},{hidden['id']})"})
    assert r.status_code == 200 and len(r.json()) == 2  # inactive rows stay readable
    r = rest(a.token).post("/exercise_videos", json={**v, "id": None, "youtube_id": "zzzzzzzzzzz"})
    assert r.status_code in (401, 403)
    r = rest(a.token).patch("/exercise_videos", params={"id": f"eq.{v['id']}"},
                            json={"title": "x"}, headers=REP)
    assert r.status_code in (401, 403) or r.json() == []
    r = rest(a.token).delete("/exercise_videos", params={"id": f"eq.{v['id']}"}, headers=REP)
    assert r.status_code in (401, 403) or r.json() == []


def test_routines_owner_only(make_user, rest):
    a, b = make_user("client"), make_user("client")
    assert _routine(rest, a).status_code == 201
    r = rest(b.token).get("/routines", params={"user_id": f"eq.{a.id}"})
    assert r.status_code == 200 and r.json() == []
    r = rest(b.token).post("/routines", json={
        "user_id": a.id, "days_per_week": 3, "level": "beginner", "equipment": "none",
        "session_min": 30, "goal": "maintain", "source": "rules", "plan": {"days": []}})
    assert r.status_code in (401, 403)


def test_one_active_routine_per_user(make_user, rest):
    a = make_user("client")
    first = _routine(rest, a)
    assert first.status_code == 201
    assert _routine(rest, a).status_code == 409
    r = rest(a.token).patch("/routines", params={"id": f"eq.{first.json()[0]['id']}"},
                            json={"active": False})
    assert r.status_code == 204
    assert _routine(rest, a).status_code == 201


def test_routine_checks(make_user, rest):
    a = make_user("client")
    r = rest(a.token).post("/routines", json={
        "user_id": a.id, "days_per_week": 7, "level": "beginner", "equipment": "none",
        "session_min": 25, "goal": "maintain", "source": "rules", "plan": {"days": []}})
    assert r.status_code == 400


def test_sessions_owner_and_routine_owner(make_user, rest):
    a, b = make_user("client"), make_user("client")
    rid = _routine(rest, a).json()[0]["id"]
    tick = {"user_id": a.id, "routine_id": rid, "day_index": 0, "done_on": "2026-11-09"}
    assert rest(a.token).post("/workout_sessions", json=tick).status_code == 201
    assert rest(a.token).post("/workout_sessions", json=tick).status_code == 409
    r = rest(b.token).post("/workout_sessions", json={**tick, "user_id": b.id})
    assert r.status_code in (401, 403)
    r = rest(b.token).get("/workout_sessions", params={"routine_id": f"eq.{rid}"})
    assert r.status_code == 200 and r.json() == []
