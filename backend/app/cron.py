"""Daily job: weekly check-in push reminders, 90-day meal photo cleanup, orphan sweep.

Runs with the Supabase service-role key, which bypasses RLS, so this is the only
request-path module allowed to read it. Logs carry user IDs and error types only:
never the key, push endpoints or subscription keys.
"""
import datetime
import json
import logging
import time
from typing import Callable

import httpx
from pywebpush import WebPushException, webpush

from . import config
from .checkin_rules import CHECKIN_DAYS, is_due
from .reminders import should_remind, yangon_today

log = logging.getLogger("calorie_tracker")

BATCH = 100
PAGE = 1000  # PostgREST's default row cap
PAYLOAD = json.dumps({"title": "Weekly check-in due", "url": "/progress.html"},
                     separators=(",", ":"))
GONE = (404, 410)
# Push services drop a TTL-0 message if the phone is unreachable right then; the next
# reminder is at least 3 days away, so keep this one for a day.
PUSH_TTL_SECONDS = 86400
RETENTION_DAYS = 90
ORPHAN_GRACE = datetime.timedelta(hours=24)  # an upload may land before its row is written
MEAL_BUCKET, PROGRESS_BUCKET = "meal-photos", "progress-photos"
# Paths per reference lookup. Each is ~80 URL chars inside the quoted in.(...) filter and
# the local gateway answers 414 at 99-100 of them, so stay well below, independent of BATCH.
REF_CHUNK = 40
REFERENCES = {MEAL_BUCKET: "/meals", PROGRESS_BUCKET: "/progress_photos"}


class CronError(RuntimeError):
    """A Supabase call failed. Carries a status or exception type, never a URL or key."""


class _Db:
    def __init__(self, client: httpx.Client):
        key = config.SUPABASE_SERVICE_ROLE_KEY
        self.client = client
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        self.root = config.SUPABASE_URL.rstrip("/")
        self.base = f"{self.root}/rest/v1"

    def storage(self, method: str, path: str, **kw) -> httpx.Response:
        return self.request(method, path, _base=f"{self.root}/storage/v1", **kw)

    def request(self, method: str, path: str, _base: str | None = None, **kw) -> httpx.Response:
        try:
            resp = self.client.request(method, (_base or self.base) + path, headers=self.headers, **kw)
        except httpx.RequestError as e:
            raise CronError(type(e).__name__) from None
        if not 200 <= resp.status_code < 300:
            raise CronError(f"Supabase returned {resp.status_code}")
        return resp

    def get_all(self, path: str, params: dict) -> list[dict]:
        rows: list[dict] = []
        while True:
            page = self.request("GET", path, params={**params, "limit": str(PAGE),
                                                     "offset": str(len(rows))}).json()
            rows += page
            if len(page) < PAGE:
                return rows


def _ids_filter(ids: list[str]) -> str:
    return f"in.({','.join(ids)})"


def _push(send: Callable, sub: dict) -> bool | None:
    """True accepted, None subscription gone (404/410), False any other failure."""
    info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
    try:
        send(info, data=PAYLOAD, vapid_private_key=config.VAPID_PRIVATE_KEY,
             vapid_claims={"sub": config.VAPID_SUBJECT}, timeout=10,
             ttl=PUSH_TTL_SECONDS)
        return True
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in GONE:
            return None
        log.warning("push_failed user_id=%s error=%s", sub["user_id"], type(e).__name__)
    except Exception as e:  # network errors and the like must not stop the run
        log.warning("push_failed user_id=%s error=%s", sub["user_id"], type(e).__name__)
    return False


def _remind_page(db: _Db, rows: list[dict], today: datetime.date, send: Callable,
                 out_of_time: Callable[[], bool]) -> int:
    ids = [r["user_id"] for r in rows]
    # Only check-ins in the last CHECKIN_DAYS-1 days matter: any of them means "not due".
    recent_from = (today - datetime.timedelta(days=CHECKIN_DAYS)).isoformat()
    latest: dict[str, datetime.date] = {}
    for c in db.get_all("/checkins", {"user_id": _ids_filter(ids), "checked_on": f"gt.{recent_from}",
                                      "select": "user_id,checked_on", "order": "id.asc"}):
        day = datetime.date.fromisoformat(c["checked_on"])
        if c["user_id"] not in latest or day > latest[c["user_id"]]:
            latest[c["user_id"]] = day
    subs: dict[str, list[dict]] = {}
    for s in db.get_all("/push_subscriptions", {"user_id": _ids_filter(ids),
                                                "select": "user_id,endpoint,p256dh,auth",
                                                "order": "id.asc"}):
        subs.setdefault(s["user_id"], []).append(s)

    reminded = 0
    for row in rows:
        if out_of_time():
            break
        uid = row["user_id"]
        last_on = row.get("last_reminded_on")
        last_on = datetime.date.fromisoformat(last_on) if last_on else None
        # An older check-in is not fetched; "none in the window" is due either way.
        due = is_due(latest.get(uid), today)
        if not subs.get(uid) or not should_remind(due, row["reminders_sent"], last_on, today):
            continue
        accepted = False
        try:
            for sub in subs[uid]:
                result = _push(send, sub)
                if result is None:
                    db.request("DELETE", "/push_subscriptions", params={
                        "user_id": f"eq.{uid}", "endpoint": f"eq.{sub['endpoint']}"})
                accepted = accepted or bool(result)
            if accepted:
                # Guard on the count we read so an overlapping run cannot double count.
                db.request("PATCH", "/client_settings",
                           json={"reminders_sent": row["reminders_sent"] + 1,
                                 "last_reminded_on": today.isoformat()},
                           params={"user_id": f"eq.{uid}",
                                   "reminders_sent": f"eq.{row['reminders_sent']}"})
        except CronError as e:  # one user's bookkeeping must not stop the others
            log.warning("reminder_record_failed user_id=%s error=%s", uid, type(e).__name__)
        if accepted:
            reminded += 1
    return reminded


class _Cleanup:
    """What one run has removed or failed on, so a photo is counted once however many
    passes (retry, 90-day, orphan sweep) touch it."""

    def __init__(self):
        self.removed: set[str] = set()
        self.failed: set[str] = set()


def _remove_object(db: _Db, bucket: str, path: str) -> None:
    db.storage("DELETE", f"/object/{bucket}", json={"prefixes": [path]})


def _record_failure(db: _Db, ref: str, exc: Exception) -> None:
    """Upsert into deletion_failures; the error column holds the exception type only."""
    err = type(exc).__name__
    try:
        rows = db.request("GET", "/deletion_failures",
                          params={"ref": f"eq.{ref}", "select": "id,attempts"}).json()
        if rows:
            db.request("PATCH", "/deletion_failures", params={"id": f"eq.{rows[0]['id']}"},
                       json={"attempts": rows[0]["attempts"] + 1, "last_error": err})
        else:
            db.request("POST", "/deletion_failures",
                       json={"kind": "storage", "ref": ref, "last_error": err})
    except CronError as e:
        log.warning("deletion_failure_record_failed error=%s", type(e).__name__)


def _try_remove(db: _Db, state: _Cleanup, bucket: str, path: str, who: str = "") -> bool:
    """`who` is an ID for the log line (meal_id=.., failure_id=..); paths are never logged."""
    ref = f"{bucket}/{path}"
    if ref in state.failed:
        return False
    if ref in state.removed:
        return True
    try:
        _remove_object(db, bucket, path)
    except CronError as e:
        log.warning("photo_remove_failed bucket=%s %s error=%s", bucket, who, type(e).__name__)
        _record_failure(db, ref, e)
        state.failed.add(ref)
        return False
    state.removed.add(ref)
    return True


def _retry_failures(db: _Db, state: _Cleanup, out_of_time: Callable[[], bool]) -> None:
    for row in db.get_all("/deletion_failures", {"select": "id,ref", "order": "id.asc"}):
        if out_of_time():
            return
        bucket, _, path = row["ref"].partition("/")
        if not path:
            continue
        if _try_remove(db, state, bucket, path, f"failure_id={row['id']}"):
            try:
                db.request("DELETE", "/deletion_failures", params={"id": f"eq.{row['id']}"})
            except CronError as e:
                log.warning("deletion_failure_clear_failed error=%s", type(e).__name__)


def _cleanup_meals(db: _Db, state: _Cleanup, now_utc: datetime.datetime,
                   out_of_time: Callable[[], bool]) -> None:
    cutoff = (yangon_today(now_utc) - datetime.timedelta(days=RETENTION_DAYS)).isoformat()
    after = 0
    while not out_of_time():
        params = {"photo_path": "not.is.null", "eaten_at": f"lt.{cutoff}",
                  "select": "id,photo_path", "order": "id.asc", "limit": str(BATCH)}
        if after:
            params["id"] = f"gt.{after}"
        rows = db.request("GET", "/meals", params=params).json()
        for row in rows:
            if out_of_time():
                return
            # Object first: a failure leaves photo_path set so the meal is tried again.
            if not _try_remove(db, state, MEAL_BUCKET, row["photo_path"], f"meal_id={row['id']}"):
                continue
            try:
                db.request("PATCH", "/meals", json={"photo_path": None}, params={
                    "id": f"eq.{row['id']}", "photo_path": f"eq.{row['photo_path']}"})
            except CronError as e:
                log.warning("meal_photo_unlink_failed meal_id=%s error=%s", row["id"], type(e).__name__)
                state.failed.add(f"meal:{row['id']}")
        if len(rows) < BATCH:
            return
        after = rows[-1]["id"]


def _list_objects(db: _Db, bucket: str, prefix: str) -> list[dict]:
    out: list[dict] = []
    while True:
        page = db.storage("POST", f"/object/list/{bucket}", json={
            "prefix": prefix, "limit": PAGE, "offset": len(out)}).json()
        out += page
        if len(page) < PAGE:
            return out


def _quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sweep_bucket(db: _Db, state: _Cleanup, bucket: str, cutoff: datetime.datetime,
                  out_of_time: Callable[[], bool]) -> None:
    for folder in [e["name"] for e in _list_objects(db, bucket, "") if not e.get("id")]:
        if out_of_time():
            return
        old = []
        for e in _list_objects(db, bucket, folder):
            if not e.get("id") or not e.get("created_at"):
                continue  # a nested folder or an entry whose age is unknown
            created = datetime.datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
            if created < cutoff:
                old.append(f"{folder}/{e['name']}")
        for i in range(0, len(old), REF_CHUNK):
            chunk = old[i:i + REF_CHUNK]
            used = {r["photo_path"] for r in db.get_all(REFERENCES[bucket], {
                "photo_path": f"in.({','.join(_quote(p) for p in chunk)})", "select": "photo_path"})}
            for path in chunk:
                if out_of_time():
                    return
                if path not in used:
                    _try_remove(db, state, bucket, path)


def _sweep_orphans(db: _Db, state: _Cleanup, now_utc: datetime.datetime,
                   out_of_time: Callable[[], bool]) -> None:
    cutoff = now_utc - ORPHAN_GRACE
    for bucket in (MEAL_BUCKET, PROGRESS_BUCKET):
        if out_of_time():
            return
        try:
            _sweep_bucket(db, state, bucket, cutoff, out_of_time)
        except CronError as e:
            log.warning("orphan_sweep_failed bucket=%s error=%s", bucket, type(e).__name__)
            state.failed.add(f"sweep:{bucket}")


def _as_db(client) -> _Db:
    return client if isinstance(client, _Db) else _Db(client)


def cleanup_meal_photos(client, now_utc: datetime.datetime, deadline: float,
                        monotonic: Callable[[], float] = time.monotonic,
                        state: _Cleanup | None = None) -> tuple[int, int]:
    """Retry earlier failures, then remove meal photos older than 90 days (Yangon date).

    `deadline` is an absolute `monotonic()` value. Returns (removed, failures); an error
    never propagates, it is counted.
    """
    db, state = _as_db(client), state or _Cleanup()
    out_of_time = lambda: monotonic() >= deadline  # noqa: E731
    for step in (lambda: _retry_failures(db, state, out_of_time),
                 lambda: _cleanup_meals(db, state, now_utc, out_of_time)):
        try:
            step()
        except CronError as e:
            log.warning("photo_cleanup_failed error=%s", type(e).__name__)
            state.failed.add(f"step:{len(state.failed)}")
    return len(state.removed), len(state.failed)


def run_daily(now_utc: datetime.datetime, send: Callable = webpush, deadline_s: float = 50,
              monotonic: Callable[[], float] = time.monotonic,
              client: httpx.Client | None = None) -> dict:
    if not config.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("service key not configured")
    started = monotonic()

    def out_of_time() -> bool:
        return monotonic() - started >= deadline_s

    today = yangon_today(now_utc)
    own_client = client is None
    client = client or httpx.Client(timeout=config.SUPABASE_TIMEOUT)
    try:
        db = _Db(client)
        reminded, after = 0, None
        while not out_of_time():
            params = {"reminders_enabled": "eq.true", "reminders_sent": "lt.2",
                      "select": "user_id,reminders_sent,last_reminded_on",
                      "order": "user_id.asc", "limit": str(BATCH)}
            if after:
                params["user_id"] = f"gt.{after}"
            rows = db.request("GET", "/client_settings", params=params).json()
            if not rows:
                break
            reminded += _remind_page(db, rows, today, send, out_of_time)
            after = rows[-1]["user_id"]
            if len(rows) < BATCH:
                break
        state = _Cleanup()
        deadline = started + deadline_s
        cleanup_meal_photos(db, now_utc, deadline, monotonic, state)
        _sweep_orphans(db, state, now_utc, out_of_time)
        return {"reminded": reminded, "photos_removed": len(state.removed),
                "failures": len(state.failed)}
    finally:
        if own_client:
            client.close()
