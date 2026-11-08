"""Store's routine requests: the PostgREST calls they make (httpx MockTransport)."""
import datetime
import json

import httpx

from app import config, store
from app.auth import User


def _mock(monkeypatch, responses):
    seen = []

    def handler(request):
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, dict(request.url.params),
                     request.headers.get("prefer"), body))
        return responses.pop(0)

    monkeypatch.setattr(store, "_http", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(config, "SUPABASE_URL", "http://db.example")
    return store.Store(User(id="u1", token="t")), seen


def test_create_routine_deactivates_then_inserts(monkeypatch):
    s, seen = _mock(monkeypatch, [httpx.Response(204), httpx.Response(201, json=[{"id": 7}])])
    assert s.create_routine({"goal": "lose"}) == {"id": 7}
    (m1, p1, q1, _, b1), (m2, p2, _, _, b2) = seen
    assert (m1, p1, q1, b1) == ("PATCH", "/rest/v1/routines",
                                {"user_id": "eq.u1", "active": "is.true"}, {"active": False})
    assert (m2, p2, b2) == ("POST", "/rest/v1/routines", {"goal": "lose", "user_id": "u1", "active": True})


def test_mark_done_ignores_duplicates(monkeypatch):
    s, seen = _mock(monkeypatch, [httpx.Response(201)])
    s.mark_done(7, 2, datetime.date(2026, 11, 9))
    method, path, params, prefer, body = seen[0]
    assert (method, path) == ("POST", "/rest/v1/workout_sessions")
    assert params == {"on_conflict": "routine_id,day_index,done_on"}
    assert "resolution=ignore-duplicates" in prefer
    assert body == {"user_id": "u1", "routine_id": 7, "day_index": 2, "done_on": "2026-11-09"}


def test_unmark_and_sessions_between(monkeypatch):
    s, seen = _mock(monkeypatch, [httpx.Response(204), httpx.Response(200, json=[
        {"day_index": 0, "done_on": "2026-11-09"}])])
    s.unmark_done(7, 2, datetime.date(2026, 11, 9))
    out = s.sessions_between(7, datetime.date(2026, 11, 9), datetime.date(2026, 11, 15))
    assert seen[0][:3] == ("DELETE", "/rest/v1/workout_sessions", {
        "user_id": "eq.u1", "routine_id": "eq.7", "day_index": "eq.2", "done_on": "eq.2026-11-09"})
    assert seen[1][2]["and"] == "(done_on.gte.2026-11-09,done_on.lte.2026-11-15)"
    assert seen[1][2]["routine_id"] == "eq.7" and seen[1][2]["user_id"] == "eq.u1"
    assert out == [{"day_index": 0, "done_on": "2026-11-09"}]


def test_videos_by_ids_skips_empty(monkeypatch):
    s, seen = _mock(monkeypatch, [httpx.Response(200, json=[{"id": 3, "title": "x"}])])
    assert s.videos_by_ids([]) == {}
    assert s.videos_by_ids([3, 3]) == {3: {"id": 3, "title": "x"}}
    assert seen[0][2]["id"] == "in.(3)"


def test_routines_created_since(monkeypatch):
    s, seen = _mock(monkeypatch, [httpx.Response(200, json=[{"id": 1}, {"id": 2}])])
    ts = datetime.datetime(2026, 11, 8, 10, 0, tzinfo=datetime.timezone.utc)
    assert s.routines_created_since(ts) == 2
    assert seen[0][2]["created_at"] == "gte.2026-11-08T10:00:00+00:00"
