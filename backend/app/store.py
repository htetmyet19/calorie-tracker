"""Supabase storage via PostgREST, acting as the logged-in user.

Every request carries the user's own JWT, so Row Level Security applies to
all queries. Errors never include response bodies or credentials.
"""
import datetime
import http.cookiejar
import threading

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

    def delete_meal(self, meal_id: int) -> bool:
        resp = self._request("DELETE", "/meals", write=True, params={
            "id": f"eq.{meal_id}", "user_id": f"eq.{self.user.id}"})
        self._check(resp)
        # RLS-filtered deletes succeed with an empty body; only a returned row counts.
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
                raise SettingsExist()
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


def get_store(user: User = Depends(current_user)) -> Store:
    return Store(user)
