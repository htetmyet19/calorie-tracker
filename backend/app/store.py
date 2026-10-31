"""Supabase storage via PostgREST, acting as the logged-in user.

Every request carries the user's own JWT, so Row Level Security applies to
all queries. Errors never include response bodies or credentials.
"""
import datetime
import http.cookiejar
import threading
from typing import Literal

import httpx
from fastapi import Depends

from . import config
from .auth import User, current_user
from .schemas import FoodItem, MealIn, MealOut, SettingsIn, WeightOut


# One pooled client per process, so warm serverless invocations reuse open TLS
# connections. No base_url: the full URL is built per request from config.
_http: httpx.Client | None = None
_http_lock = threading.Lock()


def _client() -> httpx.Client:
    global _http
    if _http is None:
        with _http_lock:
            if _http is None:
                # Empty allowed_domains: no cookie is ever stored or replayed between users.
                _http = httpx.Client(
                    timeout=config.SUPABASE_TIMEOUT,
                    cookies=http.cookiejar.CookieJar(
                        policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[])))
    return _http


class StoreUnavailable(Exception):
    """Supabase is unreachable (network error or timeout) or returned 5xx."""


class ProfileExists(Exception):
    """A profile already exists for this user."""


class SettingsExist(Exception):
    """A settings row already exists for this user."""


class EndpointTaken(Exception):
    """The push endpoint is registered to another user."""


class Store:
    def __init__(self, user: User):
        self.user = user

    def _request(self, method: str, path: str, *, params=None, json=None,
                 write: bool = False, prefer: str | None = None) -> httpx.Response:
        headers = {
            "apikey": config.SUPABASE_PUBLISHABLE_KEY,
            "Authorization": f"Bearer {self.user.token}",
        }
        if write:
            headers["Prefer"] = prefer or "return=representation"
        url = f"{config.SUPABASE_URL.rstrip('/')}/rest/v1{path}"
        try:
            resp = _client().request(method, url, params=params, json=json, headers=headers)
        except httpx.RequestError as e:
            # Report only the exception type: messages can embed URLs.
            raise StoreUnavailable(type(e).__name__) from None
        if resp.status_code >= 500:
            raise StoreUnavailable(f"Supabase returned {resp.status_code}")
        return resp

    @staticmethod
    def _check(resp: httpx.Response) -> None:
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"Supabase returned {resp.status_code}")

    @staticmethod
    def _to_meal(row: dict) -> MealOut:
        return MealOut(
            id=row["id"],
            eaten_at=row["eaten_at"][:16],  # PostgREST adds seconds
            meal_type=row["meal_type"],
            items=[FoodItem(**i) for i in row["items"]],
            total_calories=row["total_calories"],
            has_photo=row.get("photo_path") is not None,
            photo_removed=bool(row.get("photo_removed", False)),
        )

    def get_profile(self) -> dict | None:
        resp = self._request("GET", "/profiles", params={"id": f"eq.{self.user.id}"})
        self._check(resp)
        rows = resp.json()
        return rows[0] if rows else None

    def create_profile(self, role: str, display_name: str) -> dict:
        resp = self._request("POST", "/profiles", write=True, json={
            "id": self.user.id, "role": role, "display_name": display_name})
        if resp.status_code == 409:
            raise ProfileExists()
        self._check(resp)
        return resp.json()[0]

    def add_meal(self, meal: MealIn) -> MealOut:
        total = round(sum(i.calories for i in meal.items))
        resp = self._request("POST", "/meals", write=True, json={
            "user_id": self.user.id,
            "eaten_at": meal.eaten_at,
            "meal_type": meal.meal_type,
            "items": [i.model_dump() for i in meal.items],
            "total_calories": total,
        })
        self._check(resp)
        return self._to_meal(resp.json()[0])

    def meals_on(self, date: datetime.date) -> list[MealOut]:
        nxt = date + datetime.timedelta(days=1)
        # user_id filter: RLS also exposes an active trainer's clients' meals.
        resp = self._request("GET", "/meals", params={
            "user_id": f"eq.{self.user.id}",
            "and": f"(eaten_at.gte.{date.isoformat()},eaten_at.lt.{nxt.isoformat()})",
            "order": "eaten_at.asc",
        })
        self._check(resp)
        return [self._to_meal(r) for r in resp.json()]

    def daily_totals(self, start: datetime.date, end: datetime.date) -> list[dict]:
        """Calories per local day, start..end inclusive, days without meals as 0."""
        nxt = end + datetime.timedelta(days=1)
        # user_id filter: RLS also exposes an active trainer's clients' meals.
        resp = self._request("GET", "/meals", params={
            "user_id": f"eq.{self.user.id}",
            "and": f"(eaten_at.gte.{start.isoformat()},eaten_at.lt.{nxt.isoformat()})",
            "select": "eaten_at,total_calories",
        })
        self._check(resp)
        days = (end - start).days + 1
        totals = {(start + datetime.timedelta(days=i)).isoformat(): 0.0 for i in range(days)}
        for r in resp.json():
            day = r["eaten_at"][:10]
            if day in totals:
                totals[day] += float(r["total_calories"])
        return [{"date": d, "total_calories": round(t, 1)} for d, t in totals.items()]

    def delete_meal_returning(self, meal_id: int) -> dict | None:
        """Delete an own meal; return the deleted row (with photo_path) or None."""
        resp = self._request("DELETE", "/meals", write=True, params={
            "id": f"eq.{meal_id}", "user_id": f"eq.{self.user.id}"})
        self._check(resp)
        # RLS-filtered deletes succeed with an empty body; only a returned row counts.
        rows = resp.json() if resp.content else []
        return rows[0] if rows else None

    def meal_photo_path(self, meal_id: int) -> str | None | Literal[False]:
        """The meal's photo path, None if it has none, False if not found/not owner."""
        resp = self._request("GET", "/meals", params={
            "id": f"eq.{meal_id}", "user_id": f"eq.{self.user.id}", "select": "photo_path"})
        self._check(resp)
        rows = resp.json()
        return rows[0]["photo_path"] if rows else False

    def set_meal_photo(self, meal_id: int, path: str | None) -> bool:
        resp = self._request("PATCH", "/meals", write=True, json={"photo_path": path}, params={
            "id": f"eq.{meal_id}", "user_id": f"eq.{self.user.id}"})
        self._check(resp)
        return bool(resp.json()) if resp.content else False

    @staticmethod
    def _settings_row(row: dict) -> dict:
        row = dict(row)
        if row.get("activity") is not None:
            row["activity"] = round(float(row["activity"]), 3)
        return row

    def get_settings(self) -> dict | None:
        resp = self._request("GET", "/client_settings", params={"user_id": f"eq.{self.user.id}"})
        self._check(resp)
        rows = resp.json()
        return self._settings_row(rows[0]) if rows else None

    def put_settings(self, s: SettingsIn, only_if_empty: bool = False) -> dict:
        # Only user-editable fields: reminders_sent / last_reminded_on belong to the daily job.
        body = {"user_id": self.user.id, **s.model_dump(),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if only_if_empty:
            if s.goal_kcal is not None:
                body["goal_set_by"] = self.user.id
            resp = self._request("POST", "/client_settings", write=True, json=body)
            if resp.status_code == 409:
                resp = self._fill_empty_settings(s, body)
        else:
            current = self.get_settings()
            old_goal = current["goal_kcal"] if current else None
            if s.goal_kcal != old_goal:
                body["goal_set_by"] = self.user.id
            resp = self._request(
                "POST", "/client_settings", write=True, json=body,
                params={"on_conflict": "user_id"},
                prefer="resolution=merge-duplicates,return=representation")
        self._check(resp)
        return self._settings_row(resp.json()[0])

    # The values a user saves from the calculator or goal field. A row where all are
    # null exists only because of a weight log or a push subscription.
    SAVED_SETTINGS = ("height_cm", "age", "sex", "activity", "weight_goal", "goal_kcal")

    def _fill_empty_settings(self, s: SettingsIn, body: dict) -> httpx.Response:
        """Fill an existing row that has no saved values; SettingsExist otherwise.

        One PATCH filtered on the saved columns being null, so two devices racing
        cannot both win. Weight, unit and reminders flag change only when the
        caller sent them explicitly.
        """
        patch = {k: body[k] for k in (*self.SAVED_SETTINGS, "updated_at")}
        for k in ("weight_kg", "weight_unit", "reminders_enabled"):
            if k in s.model_fields_set:
                patch[k] = body[k]
        if "goal_set_by" in body:
            patch["goal_set_by"] = body["goal_set_by"]
        params = {"user_id": f"eq.{self.user.id}",
                  **{k: "is.null" for k in self.SAVED_SETTINGS}}
        resp = self._request("PATCH", "/client_settings", write=True, json=patch, params=params)
        self._check(resp)
        if not (resp.json() if resp.content else []):
            raise SettingsExist()
        return resp

    @staticmethod
    def _to_weight(row: dict) -> WeightOut:
        return WeightOut(logged_on=row["logged_on"], weight_kg=round(float(row["weight_kg"]), 2))

    def weights_between(self, start: datetime.date, end: datetime.date) -> list[WeightOut]:
        resp = self._request("GET", "/weight_logs", params={
            "user_id": f"eq.{self.user.id}",
            "and": f"(logged_on.gte.{start.isoformat()},logged_on.lte.{end.isoformat()})",
            "order": "logged_on.asc",
        })
        self._check(resp)
        return [self._to_weight(r) for r in resp.json()]

    def upsert_weight(self, day: datetime.date, kg: float) -> WeightOut:
        kg = round(kg, 2)
        resp = self._request(
            "POST", "/weight_logs", write=True,
            json={"user_id": self.user.id, "logged_on": day.isoformat(), "weight_kg": kg},
            params={"on_conflict": "user_id,logged_on"},
            prefer="resolution=merge-duplicates,return=representation")
        self._check(resp)
        out = self._to_weight(resp.json()[0])
        # Keep the profile weight in step. Upserting only this column leaves every
        # other settings column (goal, reminders, goal_set_by) untouched.
        sync = self._request(
            "POST", "/client_settings", write=True,
            json={"user_id": self.user.id, "weight_kg": kg},
            params={"on_conflict": "user_id"},
            prefer="resolution=merge-duplicates,return=minimal")
        self._check(sync)
        return out

    def delete_weight(self, day: datetime.date) -> bool:
        resp = self._request("DELETE", "/weight_logs", write=True, params={
            "user_id": f"eq.{self.user.id}", "logged_on": f"eq.{day.isoformat()}"})
        self._check(resp)
        return bool(resp.json()) if resp.content else False


    # ---- check-ins and progress photos ----

    def create_checkin(self, day: datetime.date, kg: float | None) -> dict:
        """Create a check-in; with a weight, upsert that day's weight log and link it."""
        weight_log_id = None
        if kg is not None:
            out = self.upsert_weight(day, kg)
            resp = self._request("GET", "/weight_logs", params={
                "user_id": f"eq.{self.user.id}", "logged_on": f"eq.{day.isoformat()}",
                "select": "id"})
            self._check(resp)
            weight_log_id = resp.json()[0]["id"]
            kg = out.weight_kg
        resp = self._request("POST", "/checkins", write=True, json={
            "user_id": self.user.id, "checked_on": day.isoformat(),
            "weight_log_id": weight_log_id})
        self._check(resp)
        row = resp.json()[0]
        return {"id": row["id"], "checked_on": row["checked_on"], "weight_kg": kg}

    def reset_reminders(self) -> None:
        # PATCH, not upsert: with no settings row there is nothing to reset, and a
        # check-in must not create an all-null row (it would block the one-time migration).
        resp = self._request(
            "PATCH", "/client_settings", write=True, json={"reminders_sent": 0},
            params={"user_id": f"eq.{self.user.id}"}, prefer="return=minimal")
        self._check(resp)

    def get_checkin(self, checkin_id: int) -> dict | None:
        resp = self._request("GET", "/checkins", params={
            "id": f"eq.{checkin_id}", "user_id": f"eq.{self.user.id}"})
        self._check(resp)
        rows = resp.json()
        return rows[0] if rows else None

    def list_checkins(self, limit: int) -> list[dict]:
        resp = self._request("GET", "/checkins", params={
            "user_id": f"eq.{self.user.id}",
            "select": "id,checked_on,weight_logs(weight_kg),progress_photos(id,pose,photo_path)",
            "order": "checked_on.desc,id.desc",
            "limit": str(limit),
        })
        self._check(resp)
        out = []
        for r in resp.json():
            w = r.get("weight_logs")
            out.append({
                "id": r["id"], "checked_on": r["checked_on"],
                "weight_kg": round(float(w["weight_kg"]), 2) if w else None,
                "photos": sorted(r.get("progress_photos") or [], key=lambda p: p["id"]),
            })
        return out

    def photo_for_pose(self, checkin_id: int, pose: str) -> dict | None:
        resp = self._request("GET", "/progress_photos", params={
            "checkin_id": f"eq.{checkin_id}", "pose": f"eq.{pose}",
            "user_id": f"eq.{self.user.id}"})
        self._check(resp)
        rows = resp.json()
        return rows[0] if rows else None

    def upsert_photo(self, checkin_id: int, pose: str, path: str) -> dict:
        resp = self._request(
            "POST", "/progress_photos", write=True,
            json={"user_id": self.user.id, "checkin_id": checkin_id, "pose": pose,
                  "photo_path": path},
            params={"on_conflict": "checkin_id,pose"},
            prefer="resolution=merge-duplicates,return=representation")
        self._check(resp)
        return resp.json()[0]

    def delete_photo_returning(self, photo_id: int) -> dict | None:
        resp = self._request("DELETE", "/progress_photos", write=True, params={
            "id": f"eq.{photo_id}", "user_id": f"eq.{self.user.id}"})
        self._check(resp)
        rows = resp.json() if resp.content else []
        return rows[0] if rows else None

    # ---- push subscriptions ----

    def add_push_subscription(self, endpoint: str, p256dh: str, auth: str) -> None:
        """Register this user's push endpoint (refreshing its keys) and enable reminders.

        There is no UPDATE policy, so refresh = delete own row, then insert. A unique
        violation after that means another user owns the endpoint (RLS hides their row).
        """
        own = {"user_id": f"eq.{self.user.id}", "endpoint": f"eq.{endpoint}"}
        self._check(self._request("DELETE", "/push_subscriptions", write=True,
                                  params=own, prefer="return=minimal"))
        resp = self._request("POST", "/push_subscriptions", write=True, prefer="return=minimal",
                             json={"user_id": self.user.id, "endpoint": endpoint,
                                   "p256dh": p256dh, "auth": auth})
        if resp.status_code == 409:
            raise EndpointTaken()
        self._check(resp)
        # Upsert only these two columns: a subscriber gets a settings row, and the
        # job-owned reminder counters are never touched from here.
        resp = self._request(
            "POST", "/client_settings", write=True,
            json={"user_id": self.user.id, "reminders_enabled": True},
            params={"on_conflict": "user_id"},
            prefer="resolution=merge-duplicates,return=minimal")
        self._check(resp)

    def remove_push_subscription(self, endpoint: str) -> None:
        self._check(self._request("DELETE", "/push_subscriptions", write=True, prefer="return=minimal",
                                  params={"user_id": f"eq.{self.user.id}",
                                          "endpoint": f"eq.{endpoint}"}))
        resp = self._request("GET", "/push_subscriptions", params={
            "user_id": f"eq.{self.user.id}", "select": "id", "limit": "1"})
        self._check(resp)
        if not resp.json():
            # PATCH, not upsert: no settings row means nothing to switch off.
            self._check(self._request(
                "PATCH", "/client_settings", write=True, json={"reminders_enabled": False},
                params={"user_id": f"eq.{self.user.id}"}, prefer="return=minimal"))


def get_store(user: User = Depends(current_user)) -> Store:
    return Store(user)
