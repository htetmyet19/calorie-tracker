"""Daily job: weekly check-in push reminders (photo cleanup arrives in a later task).

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


class CronError(RuntimeError):
    """A Supabase call failed. Carries a status or exception type, never a URL or key."""


class _Db:
    def __init__(self, client: httpx.Client):
        key = config.SUPABASE_SERVICE_ROLE_KEY
        self.client = client
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        self.base = f"{config.SUPABASE_URL.rstrip('/')}/rest/v1"

    def request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            resp = self.client.request(method, self.base + path, headers=self.headers, **kw)
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
             vapid_claims={"sub": config.VAPID_SUBJECT}, timeout=10)
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
                       params={"user_id": f"eq.{uid}", "reminders_sent": f"eq.{row['reminders_sent']}"})
            reminded += 1
    return reminded


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
        return {"reminded": reminded, "photos_removed": 0, "failures": 0}
    finally:
        if own_client:
            client.close()
