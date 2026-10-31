"""Supabase storage via PostgREST, acting as the logged-in user.

Every request carries the user's own JWT, so Row Level Security applies to
all queries. Errors never include response bodies or credentials.
"""
import datetime

import httpx
from fastapi import Depends

from . import config
from .auth import User, current_user
from .schemas import FoodItem, MealIn, MealOut


class StoreUnavailable(Exception):
    """Supabase is unreachable (network error or timeout) or returned 5xx."""


class ProfileExists(Exception):
    """A profile already exists for this user."""


class Store:
    def __init__(self, user: User):
        self.user = user

    def _request(self, method: str, path: str, *, params=None, json=None,
                 write: bool = False) -> httpx.Response:
        headers = {
            "apikey": config.SUPABASE_PUBLISHABLE_KEY,
            "Authorization": f"Bearer {self.user.token}",
        }
        if write:
            headers["Prefer"] = "return=representation"
        url = f"{config.SUPABASE_URL.rstrip('/')}/rest/v1{path}"
        try:
            with httpx.Client(timeout=config.SUPABASE_TIMEOUT) as client:
                resp = client.request(method, url, params=params, json=json, headers=headers)
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


def get_store(user: User = Depends(current_user)) -> Store:
    return Store(user)
