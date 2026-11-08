"""Routine routes with fake auth and Store; the AI is forced to fail so plans are rules-only."""
import datetime

import pytest
from fastapi.testclient import TestClient

from app import routine_ai
from app.auth import User, current_user
from app.main import app
from app.store import get_store
from tests.test_routine_rules import FIXTURE_LIBRARY

PROFILE = {"id": "u1", "role": "client", "display_name": "Asha"}
BODY = {"days_per_week": 3, "level": "beginner", "equipment": "none", "session_min": 30}
NOT_ENOUGH = "Not enough exercises for these choices yet. Try other equipment."


class FakeRoutineStore:
    user = User(id="u1", token="t")

    def __init__(self, videos=None, settings=None):
        self.videos = list(FIXTURE_LIBRARY if videos is None else videos)
        self.settings = settings
        self.routines = {}
        self.sessions = set()   # (routine_id, day_index, done_on iso)
        self.next_id = 1

    def get_profile(self):
        return PROFILE

    def get_settings(self):
        return self.settings

    def active_videos(self):
        return [v for v in self.videos if v["active"]]

    def videos_by_ids(self, ids):
        return {v["id"]: v for v in self.videos if v["id"] in set(ids)}

    def routines_created_since(self, ts):
        return sum(1 for r in self.routines.values()
                   if datetime.datetime.fromisoformat(r["created_at"]) >= ts)

    def create_routine(self, row):
        for r in self.routines.values():
            r["active"] = False
        saved = {**row, "id": self.next_id, "user_id": "u1", "active": True,
                 "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        self.routines[self.next_id] = saved
        self.next_id += 1
        return dict(saved)

    def active_routine(self):
        return next((dict(r) for r in self.routines.values() if r["active"]), None)

    def get_routine(self, routine_id):
        r = self.routines.get(routine_id)
        return dict(r) if r else None

    def sessions_between(self, routine_id, start, end):
        return [{"day_index": d, "done_on": on} for (rid, d, on) in sorted(self.sessions)
                if rid == routine_id and start.isoformat() <= on <= end.isoformat()]

    def mark_done(self, routine_id, day_index, day):
        self.sessions.add((routine_id, day_index, day.isoformat()))

    def unmark_done(self, routine_id, day_index, day):
        self.sessions.discard((routine_id, day_index, day.isoformat()))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    async def fail(prompt):
        raise RuntimeError("no AI in tests")
    monkeypatch.setattr(routine_ai, "ask_model", fail)
    yield
    app.dependency_overrides.clear()


def _env(store=None):
    store = store or FakeRoutineStore()
    app.dependency_overrides[current_user] = lambda: User(id="u1", token="t")
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app), store


def _today(offset=0) -> str:
    return (datetime.datetime.now(datetime.timezone.utc).date()
            + datetime.timedelta(days=offset)).isoformat()


def test_create_returns_expanded_routine():
    client, store = _env()
    r = client.post("/api/routines", json=BODY)
    assert r.status_code == 201
    body = r.json()
    assert body["source"] == "rules" and body["goal"] == "maintain" and body["note"] is None
    assert [d["title"] for d in body["days"]] == ["Full body"] * 3
    first = body["days"][0]["items"][0]
    assert first["warm_up"] is True and first["available"] is True
    assert len(first["youtube_id"]) == 11 and first["title"] and first["channel"]
    assert all(d["est_min"] <= 33 for d in body["days"])
    saved = store.routines[1]
    assert saved["fallback_reason"] == "provider_error" and saved["plan"]["days"][0]["est_min"]


def test_create_with_empty_library_is_409():
    client, _ = _env(FakeRoutineStore(videos=[]))
    r = client.post("/api/routines", json=BODY)
    assert r.status_code == 409 and r.json()["detail"] == NOT_ENOUGH


def test_goal_from_settings_and_default():
    client, _ = _env(FakeRoutineStore(settings={"weight_goal": "gain"}))
    assert client.post("/api/routines", json=BODY).json()["goal"] == "gain"


def test_goal_defaults_to_maintain():
    for settings in (None, {"weight_goal": None}):
        client, _ = _env(FakeRoutineStore(settings=settings))
        body = client.post("/api/routines", json=BODY).json()
        assert body["goal"] == "maintain"
        assert body["days"][0]["items"][1]["rest_sec"] == 60


def test_rate_limit_429():
    client, _ = _env()
    for _ in range(5):
        assert client.post("/api/routines", json=BODY).status_code == 201
    r = client.post("/api/routines", json=BODY)
    assert r.status_code == 429 and r.json()["detail"] == "You've made 5 routines today. Try again tomorrow."


def test_two_creates_leave_one_active():
    client, store = _env()
    client.post("/api/routines", json=BODY)
    client.post("/api/routines", json=BODY)
    assert [r["active"] for r in store.routines.values()] == [False, True]


def test_validation_422():
    client, _ = _env()
    for bad in ({"days_per_week": 7}, {"days_per_week": 1}, {"session_min": 25},
                {"level": "pro"}, {"equipment": "bands"}):
        assert client.post("/api/routines", json={**BODY, **bad}).status_code == 422, bad


def test_beginner_six_days_gets_note():
    client, _ = _env()
    body = client.post("/api/routines", json={**BODY, "days_per_week": 6}).json()
    assert len(body["days"]) == 4 and body["note"].startswith("Beginners recover better")


def test_active_none():
    client, _ = _env()
    r = client.get("/api/routines/active", params={"today": "2026-11-11"})
    assert r.json() == {"routine": None, "done": [], "week_start": None}


def test_active_includes_this_weeks_done():
    client, store = _env()
    rid = client.post("/api/routines", json=BODY).json()["id"]
    store.sessions |= {(rid, 0, "2026-11-08"), (rid, 1, "2026-11-09")}  # Sun, Mon
    r = client.get("/api/routines/active", params={"today": "2026-11-11"})  # Wed
    body = r.json()
    assert body["routine"]["id"] == rid and body["week_start"] == "2026-11-09"
    assert body["done"] == [{"day_index": 1, "done_on": "2026-11-09"}]


def test_active_bad_today_400():
    client, _ = _env()
    assert client.get("/api/routines/active", params={"today": "11/11/2026"}).status_code == 400


def test_inactive_video_marked_unavailable():
    client, store = _env()
    body = client.post("/api/routines", json=BODY).json()
    vid = body["days"][0]["items"][1]["video_id"]
    next(v for v in store.videos if v["id"] == vid)["active"] = False
    store.videos = [{**v} for v in store.videos]
    items = client.get("/api/routines/active", params={"today": "2026-11-11"}).json()["routine"]["days"][0]["items"]
    item = next(i for i in items if i["video_id"] == vid)
    assert item["available"] is False and item["title"]


def test_tick_and_untick_idempotent():
    client, store = _env()
    rid = client.post("/api/routines", json=BODY).json()["id"]
    url = f"/api/routines/{rid}/days/1/done/{_today()}"
    assert client.put(url).status_code == 204
    assert client.put(url).status_code == 204
    assert store.sessions == {(rid, 1, _today())}
    assert client.delete(url).status_code == 204
    assert client.delete(url).status_code == 204
    assert store.sessions == set()


def test_tick_inactive_routine_404():
    client, _ = _env()
    old = client.post("/api/routines", json=BODY).json()["id"]
    client.post("/api/routines", json=BODY)
    assert client.put(f"/api/routines/{old}/days/0/done/{_today()}").status_code == 404
    assert client.put(f"/api/routines/999/days/0/done/{_today()}").status_code == 404


def test_tick_bad_day_index_404():
    client, _ = _env()
    rid = client.post("/api/routines", json=BODY).json()["id"]
    assert client.put(f"/api/routines/{rid}/days/3/done/{_today()}").status_code == 404


def test_tick_future_date_400():
    client, _ = _env()
    rid = client.post("/api/routines", json=BODY).json()["id"]
    assert client.put(f"/api/routines/{rid}/days/0/done/{_today(1)}").status_code == 204
    assert client.put(f"/api/routines/{rid}/days/0/done/{_today(2)}").status_code == 400
    assert client.put(f"/api/routines/{rid}/days/0/done/2026-13-01").status_code == 400


def test_busy_store_is_409_not_500():
    from app.store import RoutineBusy

    class Busy(FakeRoutineStore):
        def create_routine(self, row):
            raise RoutineBusy()
    client, _ = _env(Busy())
    r = client.post("/api/routines", json=BODY)
    assert r.status_code == 409 and r.json()["detail"] == "Another routine was just built. Reload to see it."
