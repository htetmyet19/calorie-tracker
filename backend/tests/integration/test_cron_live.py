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


# ---- photo cleanup ----

def _today_yangon():
    return cron.yangon_today(datetime.now(timezone.utc))


def _meal_with_photo(service, upload_object, u, days_old, name):
    path = f"{u.id}/{name}.jpg"
    assert upload_object(u, "meal-photos", path) == 200
    eaten = datetime.combine(_today_yangon() - timedelta(days=days_old), datetime.min.time())
    r = service.post("/meals", json={
        "user_id": u.id, "eaten_at": eaten.isoformat(), "meal_type": "lunch",
        "items": [{"name": "rice"}], "total_calories": 500, "photo_path": path})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"], path


def _exists(storage, bucket, path):
    return storage.head(f"/object/authenticated/{bucket}/{path}").status_code == 200


def _photo_path(service, meal_id):
    return service.get("/meals", params={"id": f"eq.{meal_id}", "select": "photo_path"}).json()[0]["photo_path"]


def _failures(service, ref):
    return service.get("/deletion_failures", params={"ref": f"eq.{ref}"}).json()


def test_cleanup_removes_only_old_photos(make_user, service, storage, upload_object):
    u = make_user()
    old_id, old_path = _meal_with_photo(service, upload_object, u, 91, "old")
    new_id, new_path = _meal_with_photo(service, upload_object, u, 89, "new")
    import time
    cron.cleanup_meal_photos(httpx.Client(timeout=config.SUPABASE_TIMEOUT),
                             datetime.now(timezone.utc), deadline=time.monotonic() + 50)
    assert _photo_path(service, old_id) is None and not _exists(storage, "meal-photos", old_path)
    assert _photo_path(service, new_id) == new_path and _exists(storage, "meal-photos", new_path)


def test_cleanup_records_and_retries_failure(make_user, service, storage, upload_object, monkeypatch):
    import time
    u = make_user()
    meal_id, path = _meal_with_photo(service, upload_object, u, 120, "stuck")
    ref = f"meal-photos/{path}"
    real = cron._remove_object

    def flaky(db, bucket, p):
        if p == path:
            raise cron.CronError("Supabase returned 500")
        real(db, bucket, p)
    monkeypatch.setattr(cron, "_remove_object", flaky)
    with httpx.Client(timeout=config.SUPABASE_TIMEOUT) as c:
        out = cron.cleanup_meal_photos(c, datetime.now(timezone.utc), deadline=time.monotonic() + 50)
        assert out[1] >= 1
        rows = _failures(service, ref)
        assert len(rows) == 1 and rows[0]["attempts"] == 1 and rows[0]["last_error"] == "CronError"
        assert _photo_path(service, meal_id) == path and _exists(storage, "meal-photos", path)

        cron.cleanup_meal_photos(c, datetime.now(timezone.utc), deadline=time.monotonic() + 50)
        assert _failures(service, ref)[0]["attempts"] == 2

        monkeypatch.setattr(cron, "_remove_object", real)
        cron.cleanup_meal_photos(c, datetime.now(timezone.utc), deadline=time.monotonic() + 50)
    assert _failures(service, ref) == []
    assert _photo_path(service, meal_id) is None and not _exists(storage, "meal-photos", path)


def test_orphan_sweep_keeps_referenced_and_recent_objects(make_user, service, storage, upload_object):
    u = make_user()
    ck = service.post("/checkins", json={"user_id": u.id, "checked_on": "2026-10-01"}).json()[0]["id"]
    objs = {}
    for bucket in ("meal-photos", "progress-photos"):
        for kind in ("orphan", "referenced"):
            objs[bucket, kind] = f"{u.id}/{bucket[:4]}-{kind}.jpg"
            assert upload_object(u, bucket, objs[bucket, kind]) == 200
    r = service.post("/meals", json={
        "user_id": u.id, "eaten_at": datetime.now().isoformat(), "meal_type": "lunch",
        "items": [{"name": "rice"}], "total_calories": 500,
        "photo_path": objs["meal-photos", "referenced"]})
    assert r.status_code == 201
    assert service.post("/progress_photos", json={
        "user_id": u.id, "checkin_id": ck, "pose": "front",
        "photo_path": objs["progress-photos", "referenced"]}).status_code == 201

    # Just uploaded: everything is younger than 24 h, so nothing goes.
    out = cron.run_daily(datetime.now(timezone.utc), send=Sender())
    assert all(_exists(storage, b, p) for (b, _), p in objs.items())

    # Two days later the unreferenced objects are old enough; referenced ones stay.
    out = cron.run_daily(datetime.now(timezone.utc) + timedelta(days=2), send=Sender())
    assert out["photos_removed"] >= 2
    for (bucket, kind), path in objs.items():
        assert _exists(storage, bucket, path) == (kind == "referenced"), (bucket, kind)
