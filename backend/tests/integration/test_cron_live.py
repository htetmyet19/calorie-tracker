"""Daily reminder job against the local stack: real tables, real service key, fake push sender."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pywebpush import WebPushException

from app import config, cron
from app.main import app

pytestmark = pytest.mark.integration

DUE_DAY = datetime(2026, 11, 7, 2, 30, tzinfo=timezone.utc)  # Yangon 2026-11-07
LAST_CHECKIN = "2026-10-31"


class Sender:
    def __init__(self, status=None):
        self.calls, self.status = [], status

    def __call__(self, subscription_info, data=None, **kw):
        self.calls.append((subscription_info["endpoint"], data))
        if self.status:
            raise WebPushException("gone", response=httpx.Response(self.status))
        return httpx.Response(201)

    def for_endpoint(self, endpoint):
        return [c for c in self.calls if c[0] == endpoint]


@pytest.fixture
def setup(make_user, service):
    def _setup(last_checkin=LAST_CHECKIN):
        u = make_user()
        endpoint = f"https://push.example.com/{u.id}"
        assert service.post("/client_settings", json={
            "user_id": u.id, "reminders_enabled": True}).status_code == 201
        assert service.post("/push_subscriptions", json={
            "user_id": u.id, "endpoint": endpoint, "p256dh": "p", "auth": "a"}).status_code == 201
        assert service.post("/checkins", json={
            "user_id": u.id, "checked_on": last_checkin}).status_code == 201
        return u, endpoint
    return _setup


def state(service, u):
    return service.get("/client_settings", params={"user_id": f"eq.{u.id}"}).json()[0]


def test_reminder_sent_once_then_after_3_days(setup, service, monkeypatch):
    u, endpoint = setup()
    send = Sender()

    cron.run_daily(DUE_DAY, send=send)
    assert [c[1] for c in send.for_endpoint(endpoint)] == [
        '{"title":"Weekly check-in due","url":"/progress.html"}']
    s = state(service, u)
    assert s["reminders_sent"] == 1 and s["last_reminded_on"] == "2026-11-07"

    cron.run_daily(DUE_DAY + timedelta(days=1), send=send)   # next day: nothing
    cron.run_daily(DUE_DAY + timedelta(days=2), send=send)   # still inside the gap
    assert len(send.for_endpoint(endpoint)) == 1

    cron.run_daily(DUE_DAY + timedelta(days=3), send=send)   # 3 days later: second
    assert len(send.for_endpoint(endpoint)) == 2
    s = state(service, u)
    assert s["reminders_sent"] == 2 and s["last_reminded_on"] == "2026-11-10"

    cron.run_daily(DUE_DAY + timedelta(days=6), send=send)   # never a third
    assert len(send.for_endpoint(endpoint)) == 2


def test_not_due_user_gets_nothing(setup, service):
    u, endpoint = setup(last_checkin="2026-11-03")
    send = Sender()
    cron.run_daily(DUE_DAY, send=send)
    assert send.for_endpoint(endpoint) == []
    assert state(service, u)["reminders_sent"] == 0


def test_gone_subscription_is_deleted(setup, service):
    u, endpoint = setup()
    out = cron.run_daily(DUE_DAY, send=Sender(status=410))
    assert service.get("/push_subscriptions",
                       params={"user_id": f"eq.{u.id}"}).json() == []
    assert state(service, u)["reminders_sent"] == 0
    assert out["failures"] == 0


def test_cron_endpoint_requires_secret(monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "it-secret")
    with TestClient(app) as c:
        assert c.get("/api/cron/daily").status_code == 401
        r = c.get("/api/cron/daily", headers={"Authorization": "Bearer it-secret"})
    assert r.status_code == 200 and set(r.json()) == {"reminded", "photos_removed", "failures"}


def test_subscribe_routes_live(make_user, service):
    a, b = make_user(), make_user()
    ep = "https://push.example.com/live-" + a.id
    body = {"endpoint": ep, "keys": {"p256dh": "p", "auth": "a"}}
    with TestClient(app) as c:
        ha, hb = ({"Authorization": f"Bearer {u.token}"} for u in (a, b))
        assert c.post("/api/push/subscribe", headers=ha, json=body).status_code == 201
        assert c.post("/api/push/subscribe", headers=ha, json=body).status_code == 201  # idempotent
        assert c.post("/api/push/subscribe", headers=hb, json=body).status_code == 409  # not stolen
        assert state(service, a)["reminders_enabled"] is True
        assert service.get("/push_subscriptions", params={"endpoint": f"eq.{ep}"}).json()[0]["user_id"] == a.id
        assert c.request("DELETE", "/api/push/subscribe", headers=hb, json={"endpoint": ep}).status_code == 204
        assert len(service.get("/push_subscriptions", params={"endpoint": f"eq.{ep}"}).json()) == 1
        assert c.request("DELETE", "/api/push/subscribe", headers=ha, json={"endpoint": ep}).status_code == 204
    assert state(service, a)["reminders_enabled"] is False
    assert service.get("/client_settings", params={"user_id": f"eq.{b.id}"}).json() == []
