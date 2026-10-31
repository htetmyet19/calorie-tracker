"""Settings routes with fake auth and a fake Store; no network."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import store as store_mod
from app.auth import User, current_user
from app.main import app
from app.store import SettingsExist, get_store

PROFILE = {"id": "u1", "role": "client", "display_name": "Asha"}
BODY = {"height_cm": 170, "weight_kg": 70.5, "age": 30, "sex": "female", "activity": 1.375,
        "weight_goal": "lose", "goal_kcal": 1800, "weight_unit": "lb", "reminders_enabled": True}


class FakeStore:
    def __init__(self, profile=PROFILE):
        self.profile, self.row = profile, None

    def get_profile(self):
        return self.profile

    def get_settings(self):
        return self.row

    def put_settings(self, s, only_if_empty=False):
        if only_if_empty and self.row is not None:
            raise SettingsExist()
        self.row = {**s.model_dump(), "goal_set_by": "u1" if s.goal_kcal else None}
        return self.row


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


def make_client(store):
    app.dependency_overrides[current_user] = lambda: User(id="u1", token="t")
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def test_get_settings_defaults():
    r = make_client(FakeStore()).get("/api/settings")
    assert r.status_code == 200
    assert r.json() == {
        "height_cm": None, "weight_kg": None, "age": None, "sex": None, "activity": None,
        "weight_goal": None, "goal_kcal": None, "weight_unit": "kg",
        "reminders_enabled": False, "goal_set_by": None}


def test_put_settings_roundtrip():
    c = make_client(FakeStore())
    r = c.put("/api/settings", json=BODY)
    assert r.status_code == 200
    assert r.json() == {**BODY, "goal_set_by": "u1"}
    assert c.get("/api/settings").json() == {**BODY, "goal_set_by": "u1"}


@pytest.mark.parametrize("patch", [{"height_cm": 119}, {"goal_kcal": 9050}, {"activity": 1.3}])
def test_put_settings_rejects_out_of_range(patch):
    r = make_client(FakeStore()).put("/api/settings", json={**BODY, **patch})
    assert r.status_code == 422


@pytest.mark.parametrize("flag", ["1", "true"])
def test_put_only_if_empty_conflict(flag):
    c = make_client(FakeStore())
    assert c.put("/api/settings", json=BODY).status_code == 200
    r = c.put(f"/api/settings?only_if_empty={flag}", json=BODY)
    assert r.status_code == 409
    assert r.json() == {"detail": "settings_exist"}


@pytest.mark.parametrize("flag", ["0", "false"])
def test_put_only_if_empty_off_overwrites(flag):
    c = make_client(FakeStore())
    assert c.put("/api/settings", json=BODY).status_code == 200
    assert c.put(f"/api/settings?only_if_empty={flag}", json=BODY).status_code == 200


@pytest.mark.parametrize("flag", ["yes please", "2", ""])
def test_put_only_if_empty_rejects_garbage(flag):
    r = make_client(FakeStore()).put(f"/api/settings?only_if_empty={flag}", json=BODY)
    assert r.status_code == 422


def test_put_only_if_empty_when_empty_succeeds():
    r = make_client(FakeStore()).put("/api/settings?only_if_empty=1", json=BODY)
    assert r.status_code == 200


def test_settings_require_profile():
    c = make_client(FakeStore(profile=None))
    for r in (c.get("/api/settings"), c.put("/api/settings", json=BODY)):
        assert r.status_code == 409
        assert r.json() == {"detail": "choose_role"}


def test_http_client_stores_no_cookies():
    client = store_mod._client()
    req = httpx.Request("GET", "https://example.supabase.co/rest/v1/profiles")
    resp = httpx.Response(200, headers=[("set-cookie", "sid=abc; Path=/")], request=req)
    client.cookies.extract_cookies(resp)
    assert len(client.cookies) == 0
