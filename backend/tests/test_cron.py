"""Cron secret check and run_daily against an in-memory PostgREST; no network."""
import json
from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, cron
from app.main import app

client = TestClient(app)


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(cron, "run_daily",
                        lambda now: {"reminded": 2, "photos_removed": 0, "failures": 0})


def test_missing_header_is_401(monkeypatch, patched):
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    assert client.get("/api/cron/daily").status_code == 401


def test_wrong_secret_is_401(monkeypatch, patched):
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    assert client.get("/api/cron/daily", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_empty_secret_never_authorises(monkeypatch, patched):
    monkeypatch.setattr(config, "CRON_SECRET", "")
    for h in ({"Authorization": "Bearer "}, {"Authorization": ""}, {}):
        assert client.get("/api/cron/daily", headers=h).status_code == 401


def test_correct_secret_returns_counts(monkeypatch, patched):
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    r = client.get("/api/cron/daily", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.json() == {"reminded": 2, "photos_removed": 0, "failures": 0}


# ---- run_daily ----

NOW = datetime(2026, 11, 7, 2, 30, tzinfo=timezone.utc)  # Yangon 2026-11-07
PAYLOAD = '{"title":"Weekly check-in due","url":"/progress.html"}'


class FakeDb:
    """Just enough PostgREST for run_daily."""

    def __init__(self, settings, checkins, subs):
        self.settings, self.checkins, self.subs = settings, checkins, subs
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        path = request.url.path.removeprefix("/rest/v1")
        self.calls.append((request.method, path, q))
        assert request.headers["apikey"] == "svc"
        assert request.headers["authorization"] == "Bearer svc"
        if request.method == "GET" and path == "/client_settings":
            assert q["reminders_enabled"] == "eq.true" and q["reminders_sent"] == "lt.2"
            assert q["order"] == "user_id.asc" and q["limit"] == "100"
            after = q.get("user_id", "gt.").removeprefix("gt.")
            rows = sorted((r for r in self.settings if r["user_id"] > after),
                          key=lambda r: r["user_id"])[:100]
            return httpx.Response(200, json=rows)
        if request.method == "GET" and path == "/checkins":
            ids = q["user_id"].removeprefix("in.(").removesuffix(")").split(",")
            floor = q["checked_on"].removeprefix("gt.")
            return httpx.Response(200, json=[c for c in self.checkins
                                             if c["user_id"] in ids and c["checked_on"] > floor])
        if request.method == "GET" and path == "/push_subscriptions":
            ids = q["user_id"].removeprefix("in.(").removesuffix(")").split(",")
            return httpx.Response(200, json=[s for s in self.subs if s["user_id"] in ids])
        if request.method == "DELETE" and path == "/push_subscriptions":
            ep = q["endpoint"].removeprefix("eq.")
            self.subs = [s for s in self.subs if s["endpoint"] != ep]
            return httpx.Response(204)
        if request.method == "PATCH" and path == "/client_settings":
            uid = q["user_id"].removeprefix("eq.")
            sent = int(q["reminders_sent"].removeprefix("eq."))
            body = json.loads(request.content)
            for r in self.settings:
                if r["user_id"] == uid and r["reminders_sent"] == sent:
                    r.update(body)
            return httpx.Response(204)
        return httpx.Response(500)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler),
                            base_url="http://supa.test")


def sub(uid, n=1):
    return {"user_id": uid, "endpoint": f"https://push.example/{uid}/{n}", "p256dh": "p", "auth": "a"}


def srow(uid, sent=0, last=None):
    return {"user_id": uid, "reminders_sent": sent, "last_reminded_on": last}


class Sender:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def __call__(self, subscription_info, data=None, **kw):
        self.calls.append((subscription_info["endpoint"], data, kw))
        err = self.fail.get(subscription_info["endpoint"])
        if err:
            raise err
        return httpx.Response(201)


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_SERVICE_ROLE_KEY", "svc")
    monkeypatch.setattr(config, "SUPABASE_URL", "http://supa.test")
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(config, "VAPID_SUBJECT", "mailto:a@example.com")


def webpush_error(status):
    from pywebpush import WebPushException
    return WebPushException("boom", response=httpx.Response(status))


def test_sends_to_due_users_only_and_records_it():
    db = FakeDb(
        settings=[srow("a"), srow("b"), srow("c")],
        checkins=[{"user_id": "b", "checked_on": "2026-11-03"},   # b checked in 4 days ago: not due
                  {"user_id": "a", "checked_on": "2026-10-31"}],  # exactly 7 days: due
        subs=[sub("a"), sub("b"), sub("c")])
    send = Sender()
    out = cron.run_daily(NOW, send=send, client=db.client())
    assert out == {"reminded": 2, "photos_removed": 0, "failures": 0}
    assert sorted(c[0] for c in send.calls) == ["https://push.example/a/1", "https://push.example/c/1"]
    assert all(c[1] == PAYLOAD for c in send.calls)
    assert all(c[2]["vapid_private_key"] == "priv" for c in send.calls)
    assert all(c[2]["ttl"] == 86400 for c in send.calls)
    assert all(c[2]["vapid_claims"] == {"sub": "mailto:a@example.com"} for c in send.calls)
    by = {r["user_id"]: r for r in db.settings}
    assert by["a"]["reminders_sent"] == 1 and by["a"]["last_reminded_on"] == "2026-11-07"
    assert by["b"]["reminders_sent"] == 0


def test_second_reminder_waits_three_days():
    db = FakeDb([srow("a", 1, "2026-11-05"), srow("b", 1, "2026-11-04")], [], [sub("a"), sub("b")])
    send = Sender()
    out = cron.run_daily(NOW, send=send, client=db.client())
    assert out["reminded"] == 1 and [c[0] for c in send.calls] == ["https://push.example/b/1"]


def test_gone_subscription_deleted_and_other_still_counts():
    gone = sub("a", 1)
    db = FakeDb([srow("a")], [], [gone, sub("a", 2)])
    send = Sender(fail={gone["endpoint"]: webpush_error(410)})
    out = cron.run_daily(NOW, send=send, client=db.client())
    assert out["reminded"] == 1
    assert [s["endpoint"] for s in db.subs] == ["https://push.example/a/2"]


def test_all_subscriptions_gone_means_not_reminded():
    s = sub("a")
    db = FakeDb([srow("a")], [], [s])
    out = cron.run_daily(NOW, send=Sender(fail={s["endpoint"]: webpush_error(404)}), client=db.client())
    assert out["reminded"] == 0 and db.subs == []
    assert db.settings[0]["reminders_sent"] == 0


def test_other_push_errors_are_logged_without_secrets_and_do_not_stop_run(caplog):
    a, b = sub("a"), sub("b")
    db = FakeDb([srow("a"), srow("b")], [], [a, b])
    send = Sender(fail={a["endpoint"]: webpush_error(500)})
    with caplog.at_level("INFO"):
        out = cron.run_daily(NOW, send=send, client=db.client())
    assert out["reminded"] == 1 and len(db.subs) == 2
    text = caplog.text
    assert "push_failed user_id=a error=WebPushException" in text
    assert "push.example" not in text and "svc" not in text.replace("push_failed", "")


def test_network_error_does_not_stop_run():
    a = sub("a")
    db = FakeDb([srow("a"), srow("b")], [], [a, sub("b")])
    send = Sender(fail={a["endpoint"]: ConnectionError("down")})
    assert cron.run_daily(NOW, send=send, client=db.client())["reminded"] == 1


def test_user_without_subscription_is_skipped():
    db = FakeDb([srow("a")], [], [])
    send = Sender()
    assert cron.run_daily(NOW, send=send, client=db.client())["reminded"] == 0
    assert send.calls == []


def test_pages_of_100_by_keyset():
    ids = [f"u{i:03d}" for i in range(150)]
    db = FakeDb([srow(i) for i in ids], [], [sub(i) for i in ids])
    send = Sender()
    assert cron.run_daily(NOW, send=send, client=db.client())["reminded"] == 150
    pages = [c for c in db.calls if c[0] == "GET" and c[1] == "/client_settings"]
    assert len(pages) == 2


def test_deadline_stops_new_work():
    ids = [f"u{i:03d}" for i in range(150)]
    db = FakeDb([srow(i) for i in ids], [], [sub(i) for i in ids])
    send = Sender()
    ticks = iter([0.0] + [0.0] * 5 + [51.0] * 10_000)  # budget gone after a few users
    out = cron.run_daily(NOW, send=send, client=db.client(), monotonic=lambda: next(ticks))
    assert 0 < out["reminded"] < 150
    assert len(send.calls) == out["reminded"]


def test_requires_service_key(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_SERVICE_ROLE_KEY", "")
    with pytest.raises(RuntimeError, match="not configured"):
        cron.run_daily(NOW, send=Sender())
