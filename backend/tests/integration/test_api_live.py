"""The API end to end: real Supabase tokens through auth, Store and RLS."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration

ITEM = {"name": "dal", "portion": "1 bowl", "grams": 200, "calories": 150,
        "protein_g": 8, "carbs_g": 20, "fat_g": 3, "confidence": "high"}
MEAL = {"eaten_at": "2026-10-31T08:00", "meal_type": "breakfast", "items": [ITEM]}


@pytest.fixture
def api():
    with TestClient(app) as c:
        yield c


def auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


def test_new_user_chooses_role_then_logs_a_meal(api, make_user):
    u = auth(make_user(role=None))
    r = api.get("/api/me", headers=u)
    assert (r.status_code, r.json()) == (404, {"detail": "no_profile"})

    r = api.post("/api/me/role", headers=u, json={"role": "client", "display_name": "Asha"})
    assert r.status_code == 201
    assert (r.json()["role"], r.json()["display_name"]) == ("client", "Asha")

    r = api.post("/api/meals", headers=u, json=MEAL)
    assert r.status_code == 201
    meal_id = r.json()["id"]

    r = api.get("/api/meals", headers=u, params={"date": "2026-10-31"})
    assert r.status_code == 200
    assert [m["id"] for m in r.json()["meals"]] == [meal_id]
    assert r.json()["total_calories"] == 150


def test_other_user_sees_none_of_my_meals(api, make_user):
    me, other = auth(make_user()), auth(make_user())
    assert api.post("/api/meals", headers=me, json=MEAL).status_code == 201
    r = api.get("/api/meals", headers=other, params={"date": "2026-10-31"})
    assert r.status_code == 200
    assert r.json()["meals"] == []


def test_missing_token_is_401(api):
    r = api.get("/api/meals", params={"date": "2026-10-31"})
    assert (r.status_code, r.json()) == (401, {"detail": "not_logged_in"})


def test_user_without_profile_must_choose_role(api, make_user):
    r = api.get("/api/meals", headers=auth(make_user(role=None)), params={"date": "2026-10-31"})
    assert (r.status_code, r.json()) == (409, {"detail": "choose_role"})
