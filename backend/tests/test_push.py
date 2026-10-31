"""Push subscription routes with fake auth and a fake Store; no network."""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth import User, current_user
from app.main import app
from app.store import EndpointTaken, get_store

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
BODY = {"endpoint": ENDPOINT, "keys": {"p256dh": "pk", "auth": "ak"}}


class FakeStore:
    def __init__(self, taken=False):
        self.subs, self.reminders_enabled, self.taken = {}, False, taken

    def get_profile(self):
        return {"id": "u1", "role": "client", "display_name": "A"}

    def add_push_subscription(self, endpoint, p256dh, auth):
        if self.taken:
            raise EndpointTaken()
        self.subs[endpoint] = (p256dh, auth)
        self.reminders_enabled = True

    def remove_push_subscription(self, endpoint):
        self.subs.pop(endpoint, None)
        if not self.subs:
            self.reminders_enabled = False


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


def make_client(store):
    app.dependency_overrides[current_user] = lambda: User(id="u1", token="t")
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def test_subscribe_creates_and_enables_reminders():
    s = FakeStore()
    r = make_client(s).post("/api/push/subscribe", json=BODY)
    assert r.status_code == 201
    assert s.subs == {ENDPOINT: ("pk", "ak")} and s.reminders_enabled is True


@pytest.mark.parametrize("endpoint", ["http://push.example.com/x", "ftp://x.example/y", "nope"])
def test_subscribe_rejects_non_https(endpoint):
    r = make_client(FakeStore()).post("/api/push/subscribe", json={**BODY, "endpoint": endpoint})
    assert r.status_code == 422


def test_subscribe_rejects_missing_keys():
    r = make_client(FakeStore()).post("/api/push/subscribe", json={"endpoint": ENDPOINT, "keys": {}})
    assert r.status_code == 422


def test_subscribe_other_users_endpoint_is_409():
    r = make_client(FakeStore(taken=True)).post("/api/push/subscribe", json=BODY)
    assert r.status_code == 409


def test_unsubscribe_disables_when_none_left():
    s = FakeStore()
    c = make_client(s)
    c.post("/api/push/subscribe", json=BODY)
    r = c.request("DELETE", "/api/push/subscribe", json={"endpoint": ENDPOINT})
    assert r.status_code == 204
    assert s.subs == {} and s.reminders_enabled is False


def test_public_key_503_when_unset(monkeypatch):
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", "")
    assert make_client(FakeStore()).get("/api/push/public-key").status_code == 503


def test_public_key_returned(monkeypatch):
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", "BPUB")
    r = make_client(FakeStore()).get("/api/push/public-key")
    assert r.status_code == 200 and r.json() == {"key": "BPUB"}
