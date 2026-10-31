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

    def __init__(self, settings=(), checkins=(), subs=(), meals=(), objects=None,
                 failures=(), progress=(), remove_fail=(), patch_fail=(), delete_fail=()):
        self.settings, self.checkins, self.subs = list(settings), list(checkins), list(subs)
        self.meals = list(meals)                       # {"id","user_id","eaten_at","photo_path"}
        self.objects = objects if objects is not None else {}  # bucket -> {path: created_at}
        self.failures = list(failures)                 # deletion_failures rows
        self.progress = list(progress)                 # {"photo_path"}
        self.remove_fail, self.patch_fail, self.delete_fail = set(remove_fail), set(patch_fail), set(delete_fail)
        self.calls, self.urls = [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls.append((request.method, str(request.url)))
        q = dict(request.url.params)
        path = request.url.path.removeprefix("/rest/v1")
        self.calls.append((request.method, path, q))
        assert request.headers["apikey"] == "svc"
        assert request.headers["authorization"] == "Bearer svc"
        r = self.extra(request, path, q)
        if r is not None:
            return r
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
            if q["user_id"].removeprefix("eq.") in self.delete_fail:
                return httpx.Response(500)
            self.subs = [s for s in self.subs if s["endpoint"] != ep]
            return httpx.Response(204)
        if request.method == "PATCH" and path == "/client_settings":
            uid = q["user_id"].removeprefix("eq.")
            if uid in self.patch_fail:
                return httpx.Response(500)
            sent = int(q["reminders_sent"].removeprefix("eq."))
            body = json.loads(request.content)
            for r in self.settings:
                if r["user_id"] == uid and r["reminders_sent"] == sent:
                    r.update(body)
            return httpx.Response(204)
        return httpx.Response(500)

    @staticmethod
    def _in(value):
        inner = value.removeprefix("in.(").removesuffix(")")
        return [x.strip('"') for x in inner.split('","')] if inner.startswith('"') else inner.split(",")

    def extra(self, request, path, q):
        """Meals, progress photos, deletion_failures and Storage."""
        m = request.method
        body = json.loads(request.content) if request.content else None
        if path == "/meals" and m == "GET" and q["photo_path"].startswith("in."):
            wanted = self._in(q["photo_path"])
            return httpx.Response(200, json=[{"photo_path": x["photo_path"]} for x in self.meals
                                             if x["photo_path"] in wanted])
        if path == "/progress_photos" and m == "GET":
            wanted = self._in(q["photo_path"])
            return httpx.Response(200, json=[x for x in self.progress if x["photo_path"] in wanted])
        if path == "/meals" and m == "GET":
            assert q["photo_path"] == "not.is.null" and q["order"] == "id.asc" and q["limit"] == "100"
            cutoff, after = q["eaten_at"].removeprefix("lt."), int(q.get("id", "gt.0").removeprefix("gt."))
            rows = [{"id": x["id"], "photo_path": x["photo_path"]} for x in sorted(self.meals, key=lambda x: x["id"])
                    if x["photo_path"] and x["eaten_at"] < cutoff and x["id"] > after]
            return httpx.Response(200, json=rows[:100])
        if path == "/meals" and m == "PATCH":
            assert body == {"photo_path": None}
            for x in self.meals:
                if x["id"] == int(q["id"].removeprefix("eq.")) and x["photo_path"] == q["photo_path"].removeprefix("eq."):
                    x["photo_path"] = None
            return httpx.Response(204)
        if path == "/deletion_failures":
            if m == "GET" and "ref" in q:
                ref = q["ref"].removeprefix("eq.")
                return httpx.Response(200, json=[x for x in self.failures if x["ref"] == ref])
            if m == "GET":
                off = int(q["offset"])
                return httpx.Response(200, json=sorted(self.failures, key=lambda x: x["id"])[off:off + int(q["limit"])])
            if m == "POST":
                self.failures.append({"id": len(self.failures) + 100, "attempts": 1, **body})
                return httpx.Response(201)
            if m == "PATCH":
                for x in self.failures:
                    if x["id"] == int(q["id"].removeprefix("eq.")):
                        x.update(body)
                return httpx.Response(204)
            if m == "DELETE":
                self.failures = [x for x in self.failures if x["id"] != int(q["id"].removeprefix("eq."))]
                return httpx.Response(204)
        if path.startswith("/storage/v1/object/list/"):
            bucket = path.rsplit("/", 1)[1]
            prefix = body["prefix"]
            objs = self.objects.get(bucket, {})
            if prefix == "":
                names = sorted({p.split("/")[0] for p in objs})
                entries = [{"name": n, "id": None, "created_at": None} for n in names]
            else:
                entries = [{"name": p.split("/", 1)[1], "id": "x", "created_at": c}
                           for p, c in sorted(objs.items()) if p.startswith(prefix + "/")]
            return httpx.Response(200, json=entries[body["offset"]:body["offset"] + body["limit"]])
        if path.startswith("/storage/v1/object/") and m == "DELETE":
            bucket = path.rsplit("/", 1)[1]
            for p in body["prefixes"]:
                if p in self.remove_fail:
                    return httpx.Response(500)
                self.objects.get(bucket, {}).pop(p, None)
            return httpx.Response(200, json=[])
        return None

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


# ---- reminders: per-user robustness ----

def test_settings_patch_failure_is_logged_and_run_continues(caplog):
    db = FakeDb([srow("a"), srow("b")], [], [sub("a"), sub("b")], patch_fail=["a"])
    send = Sender()
    with caplog.at_level("INFO"):
        out = cron.run_daily(NOW, send=send, client=db.client())
    assert len(send.calls) == 2 and out["reminded"] == 2   # a's push went out; only its record failed
    assert [r["reminders_sent"] for r in db.settings] == [0, 1]
    assert "reminder_record_failed user_id=a error=CronError" in caplog.text
    assert "svc" not in caplog.text.replace("reminder_record_failed", "")


def test_gone_delete_failure_is_logged_and_run_continues(caplog):
    a = sub("a")
    db = FakeDb([srow("a"), srow("b")], [], [a, sub("b")], delete_fail=["a"])
    send = Sender(fail={a["endpoint"]: webpush_error(410)})
    with caplog.at_level("INFO"):
        out = cron.run_daily(NOW, send=send, client=db.client())
    assert out["reminded"] == 1
    assert "reminder_record_failed user_id=a error=CronError" in caplog.text


# ---- photo cleanup ----
# Yangon today 2026-11-07, so the cutoff is 2026-08-09 00:00.

def meal(i, eaten, path="u1/f.jpg"):
    return {"id": i, "user_id": "u1", "eaten_at": eaten, "photo_path": path}


def test_cleanup_removes_object_then_nulls_path_for_old_meals_only():
    db = FakeDb(meals=[meal(1, "2026-08-08T23:59:00", "u1/old.jpg"),
                       meal(2, "2026-08-09T00:00:00", "u1/edge.jpg"),
                       meal(3, "2026-10-01T10:00:00", "u1/new.jpg")],
                objects={"meal-photos": {p: "2026-10-30T00:00:00Z" for p in
                                         ("u1/old.jpg", "u1/edge.jpg", "u1/new.jpg")}})
    removed, failed = cron.cleanup_meal_photos(db.client(), NOW, deadline=float("inf"))
    assert (removed, failed) == (1, 0)
    assert set(db.objects["meal-photos"]) == {"u1/edge.jpg", "u1/new.jpg"}
    assert [m["photo_path"] for m in db.meals] == [None, "u1/edge.jpg", "u1/new.jpg"]


def test_failed_removal_keeps_path_records_failure_then_retry_clears_it():
    db = FakeDb(meals=[meal(1, "2026-01-01T10:00:00", "u1/a.jpg")],
                objects={"meal-photos": {"u1/a.jpg": "2026-01-01T00:00:00Z"}},
                remove_fail=["u1/a.jpg"])
    out = cron.run_daily(NOW, send=Sender(), client=db.client())
    assert out["photos_removed"] == 0 and out["failures"] == 1   # once, not once per pass
    assert db.meals[0]["photo_path"] == "u1/a.jpg"
    assert [(f["kind"], f["ref"], f["attempts"], f["last_error"]) for f in db.failures] == [
        ("storage", "meal-photos/u1/a.jpg", 1, "CronError")]

    cron.run_daily(NOW, send=Sender(), client=db.client())
    assert db.failures[0]["attempts"] == 2

    db.remove_fail.clear()
    out = cron.run_daily(NOW, send=Sender(), client=db.client())
    assert out["photos_removed"] == 1 and out["failures"] == 0   # retry + main pass count one photo
    assert db.failures == [] and db.meals[0]["photo_path"] is None and db.objects["meal-photos"] == {}


def test_retry_runs_before_new_cleanup():
    db = FakeDb(failures=[{"id": 1, "kind": "storage", "ref": "progress-photos/u1/p.jpg",
                           "attempts": 3, "last_error": "CronError"}],
                objects={"progress-photos": {"u1/p.jpg": "2026-10-30T00:00:00Z"}},
                progress=[{"photo_path": "u1/p.jpg"}])
    removed, failed = cron.cleanup_meal_photos(db.client(), NOW, deadline=float("inf"))
    assert (removed, failed) == (1, 0)
    assert db.failures == [] and db.objects["progress-photos"] == {}


def test_cleanup_failure_never_aborts_run_or_reminders():
    db = FakeDb([srow("a")], [], [sub("a")], meals=[meal(1, "2026-01-01T10:00:00", "u1/a.jpg"),
                                                    meal(2, "2026-01-01T10:00:00", "u1/b.jpg")],
                objects={"meal-photos": {"u1/a.jpg": "2026-01-01T00:00:00Z", "u1/b.jpg": "2026-01-01T00:00:00Z"}},
                remove_fail=["u1/a.jpg"])
    out = cron.run_daily(NOW, send=Sender(), client=db.client())
    assert out == {"reminded": 1, "photos_removed": 1, "failures": 1}
    assert list(db.objects["meal-photos"]) == ["u1/a.jpg"]


def test_deadline_stops_cleanup_batches():
    meals = [meal(i, "2026-01-01T10:00:00", f"u1/{i}.jpg") for i in range(1, 251)]
    db = FakeDb(meals=meals, objects={"meal-photos": {m["photo_path"]: "2026-01-01T00:00:00Z" for m in meals}})
    clock = {"t": 0.0}

    def mono():
        return clock["t"]

    orig = db.extra

    def ticking(request, path, q):
        if request.method == "DELETE" and path.startswith("/storage/"):
            clock["t"] += 1.0                      # each removal costs one fake second
        return orig(request, path, q)
    db.extra = ticking
    out = cron.run_daily(NOW, send=Sender(), client=db.client(), deadline_s=30, monotonic=mono)
    assert 0 < out["photos_removed"] < 250


# ---- orphan sweep ----

def test_orphan_sweep_removes_old_unreferenced_in_both_buckets_only():
    old, young = "2026-11-05T00:00:00Z", "2026-11-06T12:00:00Z"      # NOW is 2026-11-07T02:30Z
    db = FakeDb(meals=[meal(1, "2026-11-01T10:00:00", "u1/kept-meal.jpg")],
                progress=[{"photo_path": "u2/kept-prog.jpg"}],
                objects={"meal-photos": {"u1/kept-meal.jpg": old, "u1/orphan.jpg": old,
                                         "u1/young.jpg": young},
                         "progress-photos": {"u2/kept-prog.jpg": old, "u2/orphan.jpg": old,
                                             "u2/young.jpg": young}})
    out = cron.run_daily(NOW, send=Sender(), client=db.client())
    assert out["photos_removed"] == 2 and out["failures"] == 0
    assert set(db.objects["meal-photos"]) == {"u1/kept-meal.jpg", "u1/young.jpg"}
    assert set(db.objects["progress-photos"]) == {"u2/kept-prog.jpg", "u2/young.jpg"}


def test_orphan_removal_failure_goes_to_deletion_failures():
    old = "2026-11-05T00:00:00Z"
    db = FakeDb(objects={"meal-photos": {"u1/orphan.jpg": old}}, remove_fail=["u1/orphan.jpg"])
    out = cron.run_daily(NOW, send=Sender(), client=db.client())
    assert out["photos_removed"] == 0 and out["failures"] == 1
    assert db.failures[0]["ref"] == "meal-photos/u1/orphan.jpg"


def test_reference_lookups_stay_under_url_limit():
    import uuid
    old = "2026-11-05T00:00:00Z"
    uid = str(uuid.uuid4())
    paths = [f"{uid}/{uuid.uuid4().hex}.jpg" for _ in range(250)]
    db = FakeDb(meals=[meal(i, "2026-11-01T10:00:00", p) for i, p in enumerate(paths[:50], 1)],
                objects={"meal-photos": {p: old for p in paths}})
    out = cron.run_daily(NOW, send=Sender(), client=db.client())
    lookups = [u for m, u in db.urls if m == "GET" and "photo_path=in." in u]
    assert len(lookups) >= 250 // 40 and max(len(u) for u in lookups) < 4000
    assert out["photos_removed"] == 200 and out["failures"] == 0
    assert set(db.objects["meal-photos"]) == set(paths[:50])


def test_logs_carry_ids_not_paths(caplog):
    old = "2026-11-05T00:00:00Z"
    db = FakeDb(meals=[meal(1, "2026-01-01T10:00:00", "u1/secret-a.jpg")],
                failures=[{"id": 7, "kind": "storage", "ref": "meal-photos/u1/secret-b.jpg",
                           "attempts": 1, "last_error": "CronError"}],
                objects={"meal-photos": {"u1/secret-a.jpg": old, "u1/secret-b.jpg": old,
                                         "u1/secret-c.jpg": old}},
                remove_fail=["u1/secret-a.jpg", "u1/secret-b.jpg", "u1/secret-c.jpg"])
    with caplog.at_level("INFO", logger="calorie_tracker"):
        cron.run_daily(NOW, send=Sender(), client=db.client())
    msgs = [r.getMessage() for r in caplog.records if r.name == "calorie_tracker"]
    assert any("photo_remove_failed" in m for m in msgs)
    assert not any("secret" in m or "u1/" in m for m in msgs)
    assert any("failure_id=7" in m for m in msgs) and any("meal_id=1" in m for m in msgs)
