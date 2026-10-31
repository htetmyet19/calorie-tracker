"""Store's HTTP client handling; no network (httpx MockTransport)."""
import httpx

from app import config, store
from app.auth import User


def test_requests_share_one_client_and_follow_config_url(monkeypatch):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    monkeypatch.setattr(store, "_http", httpx.Client(transport=httpx.MockTransport(handler)))
    s = store.Store(User(id="u1", token="t"))
    monkeypatch.setattr(config, "SUPABASE_URL", "http://a.example/")
    s.get_profile()
    monkeypatch.setattr(config, "SUPABASE_URL", "http://b.example")
    s.get_profile()
    assert [u.split("?")[0] for u in seen] == [
        "http://a.example/rest/v1/profiles", "http://b.example/rest/v1/profiles"]
    assert store._client() is store._client()


# ---------- put_settings(only_if_empty=True) (ruling R7) ----------

import json as _json  # noqa: E402

import pytest  # noqa: E402

from app.schemas import SettingsIn  # noqa: E402

CALC_FIELDS = ("height_cm", "age", "sex", "activity", "weight_goal", "goal_kcal")


def _mock(monkeypatch, responses):
    """Serve canned responses in order; record (method, url, json body)."""
    seen = []

    def handler(request):
        body = _json.loads(request.content) if request.content else None
        seen.append((request.method, request.url, body))
        return responses.pop(0)

    monkeypatch.setattr(store, "_http", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(config, "SUPABASE_URL", "http://db.example")
    return seen


def test_only_if_empty_inserts_when_no_row(monkeypatch):
    row = {"user_id": "u1", "goal_kcal": 1800, "activity": "1.550"}
    seen = _mock(monkeypatch, [httpx.Response(201, json=[row])])
    out = store.Store(User(id="u1", token="t")).put_settings(
        SettingsIn(goal_kcal=1800, activity=1.55), only_if_empty=True)
    assert out["activity"] == 1.55
    assert [m for m, _, _ in seen] == ["POST"]
    assert seen[0][2]["goal_set_by"] == "u1"


def test_only_if_empty_fills_a_row_without_calculator_values(monkeypatch):
    # The row exists only because a weight was logged: the move fills it in.
    row = {"user_id": "u1", "weight_kg": "71.25", "goal_kcal": 1800, "reminders_enabled": True}
    seen = _mock(monkeypatch, [httpx.Response(409, json={"code": "23505"}),
                               httpx.Response(200, json=[row])])
    out = store.Store(User(id="u1", token="t")).put_settings(
        SettingsIn(height_cm=170, age=30, sex="female", activity=1.375,
                   weight_goal="lose", goal_kcal=1800), only_if_empty=True)
    assert out["goal_kcal"] == 1800
    method, url, body = seen[1]
    assert method == "PATCH"
    assert url.params["user_id"] == "eq.u1"
    for f in CALC_FIELDS:
        assert url.params[f] == "is.null"  # only a row with no saved values is filled
    assert {f: body[f] for f in CALC_FIELDS} == {
        "height_cm": 170, "age": 30, "sex": "female", "activity": 1.375,
        "weight_goal": "lose", "goal_kcal": 1800}
    assert body["goal_set_by"] == "u1"
    # Not sent by the caller: the logged weight, unit and reminders flag stay as they are.
    for f in ("weight_kg", "weight_unit", "reminders_enabled", "user_id"):
        assert f not in body


def test_only_if_empty_fill_includes_fields_the_caller_set(monkeypatch):
    seen = _mock(monkeypatch, [httpx.Response(409, json={}), httpx.Response(200, json=[{}])])
    store.Store(User(id="u1", token="t")).put_settings(
        SettingsIn(goal_kcal=1800, weight_kg=70, weight_unit="lb"), only_if_empty=True)
    body = seen[1][2]
    assert body["weight_kg"] == 70 and body["weight_unit"] == "lb"
    assert "reminders_enabled" not in body


def test_only_if_empty_conflicts_when_row_has_saved_values(monkeypatch):
    # PATCH filtered on all-null calculator fields matches nothing: settings exist.
    _mock(monkeypatch, [httpx.Response(409, json={}), httpx.Response(200, json=[])])
    with pytest.raises(store.SettingsExist):
        store.Store(User(id="u1", token="t")).put_settings(
            SettingsIn(goal_kcal=1800), only_if_empty=True)


def test_meal_out_carries_photo_removed():
    row = {"id": 1, "eaten_at": "2026-07-01T08:00:00", "meal_type": "lunch",
           "items": [{"name": "rice", "portion": "1 plate", "grams": 200, "calories": 260,
                      "protein_g": 5, "carbs_g": 56, "fat_g": 1, "confidence": "high"}],
           "total_calories": 0, "photo_path": None}
    assert store.Store._to_meal({**row, "photo_removed": True}).photo_removed is True
    assert store.Store._to_meal(row).photo_removed is False
    assert store.Store._to_meal({**row, "photo_path": "u1/a.jpg"}).has_photo is True
