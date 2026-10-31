"""GET /api/meals/daily-totals and Store.daily_totals; no network."""
import datetime
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, store
from app.auth import User, current_user
from app.main import app
from app.store import get_store
from tests.test_api import PROFILE, FakeStore


class TotalsStore(FakeStore):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = []

    def daily_totals(self, start, end):
        self.calls.append((start, end))
        days = (end - start).days + 1
        return [{"date": (start + datetime.timedelta(days=i)).isoformat(), "total_calories": 0.0}
                for i in range(days)]


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def fake():
    return TotalsStore(profile=dict(PROFILE))


@pytest.fixture
def client(fake):
    app.dependency_overrides[current_user] = lambda: User(id="u1", token="t")
    app.dependency_overrides[get_store] = lambda: fake
    return TestClient(app)


def test_route_returns_store_totals(client, fake):
    r = client.get("/api/meals/daily-totals", params={"from": "2026-10-25", "to": "2026-10-31"})
    assert r.status_code == 200
    assert len(r.json()) == 7
    assert r.json()[0] == {"date": "2026-10-25", "total_calories": 0.0}
    assert fake.calls == [(datetime.date(2026, 10, 25), datetime.date(2026, 10, 31))]


def test_31_days_allowed_32_rejected(client):
    ok = client.get("/api/meals/daily-totals", params={"from": "2026-10-01", "to": "2026-10-31"})
    assert ok.status_code == 200 and len(ok.json()) == 31
    r = client.get("/api/meals/daily-totals", params={"from": "2026-10-01", "to": "2026-11-01"})
    assert r.status_code == 400


@pytest.mark.parametrize("params", [
    {"from": "2026-10-31", "to": "2026-10-30"},
    {"from": "2026-02-30", "to": "2026-03-01"},
    {"from": "2026-10-1", "to": "2026-10-31"},
])
def test_bad_ranges_400(client, params):
    assert client.get("/api/meals/daily-totals", params=params).status_code == 400


def test_from_and_to_required(client):
    assert client.get("/api/meals/daily-totals", params={"from": "2026-10-01"}).status_code == 422


# ---------- Store.daily_totals against a mocked PostgREST ----------

def _mock(monkeypatch, rows):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=rows)

    monkeypatch.setattr(store, "_http", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(config, "SUPABASE_URL", "http://db.example")
    return seen


def test_store_sums_per_day_and_zero_fills(monkeypatch):
    seen = _mock(monkeypatch, [
        {"eaten_at": "2026-10-29T08:00:00", "total_calories": 400},
        {"eaten_at": "2026-10-29T13:30:00", "total_calories": 650.5},
        {"eaten_at": "2026-10-31T23:59:00", "total_calories": 300},
    ])
    out = store.Store(User(id="u1", token="t")).daily_totals(
        datetime.date(2026, 10, 28), datetime.date(2026, 10, 31))
    assert out == [
        {"date": "2026-10-28", "total_calories": 0.0},
        {"date": "2026-10-29", "total_calories": 1050.5},
        {"date": "2026-10-30", "total_calories": 0.0},
        {"date": "2026-10-31", "total_calories": 300.0},
    ]
    params = seen[0].url.params
    assert seen[0].url.path == "/rest/v1/meals"
    assert params["user_id"] == "eq.u1"  # RLS also shows a trainer's clients' meals
    assert params["and"] == "(eaten_at.gte.2026-10-28,eaten_at.lt.2026-11-01)"
    assert params["select"] == "eaten_at,total_calories"


def test_store_error_status_raises(monkeypatch):
    monkeypatch.setattr(store, "_http", httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"message": "bad"}))))
    monkeypatch.setattr(config, "SUPABASE_URL", "http://db.example")
    with pytest.raises(RuntimeError):
        store.Store(User(id="u1", token="t")).daily_totals(
            datetime.date(2026, 10, 28), datetime.date(2026, 10, 31))
