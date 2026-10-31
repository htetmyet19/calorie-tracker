"""API routes with fake auth and a fake Store; no network."""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth import User, current_user
from app.main import app
from app.schemas import MealOut
from app.store import ProfileExists, StoreUnavailable, get_store

ITEM = {"name": "dal", "portion": "1 bowl", "grams": 200, "calories": 150.4,
        "protein_g": 8.25, "carbs_g": 20.1, "fat_g": 3.04, "confidence": "high"}
ITEM2 = {**ITEM, "name": "rice", "calories": 200, "protein_g": 4.0, "carbs_g": 44.0, "fat_g": 0.5}
MEAL = {"eaten_at": "2026-10-31T08:00", "meal_type": "breakfast", "items": [ITEM]}


class FakeStore:
    def __init__(self, profile=None, down=False, delete_result=True):
        self.profile, self.down, self.delete_result = profile, down, delete_result
        self.meals = []

    def _check(self):
        if self.down:
            raise StoreUnavailable("down")

    def get_profile(self):
        self._check()
        return self.profile

    def create_profile(self, role, display_name):
        self._check()
        if self.profile:
            raise ProfileExists()
        self.profile = {"id": "u1", "role": role, "display_name": display_name}
        return self.profile

    def add_meal(self, meal):
        self._check()
        out = MealOut(id=len(self.meals) + 1, total_calories=round(sum(i.calories for i in meal.items)),
                      **meal.model_dump())
        self.meals.append(out)
        return out

    def meals_on(self, date):
        self._check()
        return [m for m in self.meals if m.eaten_at.startswith(date.isoformat())]

    def delete_meal(self, meal_id):
        self._check()
        return self.delete_result


PROFILE = {"id": "u1", "role": "client", "display_name": "Asha"}


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


def make_client(store):
    app.dependency_overrides[current_user] = lambda: User(id="u1", token="t")
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


@pytest.fixture
def anon_client():
    return TestClient(app)


@pytest.fixture
def client():
    return make_client(FakeStore(profile=dict(PROFILE)))


@pytest.fixture
def client_without_profile():
    return make_client(FakeStore())


@pytest.fixture
def client_store_down():
    return make_client(FakeStore(profile=dict(PROFILE), down=True))


def test_meals_require_login(anon_client):
    assert anon_client.get("/api/meals?date=2026-10-31").status_code == 401
    assert anon_client.post("/api/meals", json=MEAL).status_code == 401
    assert anon_client.delete("/api/meals/1").status_code == 401


def test_analyze_requires_login(anon_client):
    r = anon_client.post("/api/analyze", files={"photo": ("a.png", b"\x89PNG", "image/png")})
    assert r.status_code == 401
    assert r.json() == {"detail": "not_logged_in"}


def test_health_stays_public(anon_client, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    assert anon_client.get("/api/health").status_code == 200


def test_public_config_has_only_public_keys(anon_client):
    r = anon_client.get("/api/public-config")
    assert r.status_code == 200
    assert set(r.json()) == {"supabase_url", "supabase_publishable_key"}


def test_me_without_profile_is_404(client_without_profile):
    r = client_without_profile.get("/api/me")
    assert r.status_code == 404
    assert r.json() == {"detail": "no_profile"}


def test_me_returns_profile(client):
    assert client.get("/api/me").json() == PROFILE


def test_role_creates_profile(client_without_profile):
    r = client_without_profile.post("/api/me/role", json={"role": "trainer", "display_name": "  Ravi "})
    assert r.status_code == 201
    assert r.json() == {"id": "u1", "role": "trainer", "display_name": "Ravi"}


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_role_bad_display_name_is_422(client_without_profile, name):
    r = client_without_profile.post("/api/me/role", json={"role": "client", "display_name": name})
    assert r.status_code == 422


def test_no_profile_gets_choose_role(client_without_profile):
    for r in (client_without_profile.get("/api/meals?date=2026-10-31"),
              client_without_profile.post("/api/meals", json=MEAL),
              client_without_profile.delete("/api/meals/1")):
        assert r.status_code == 409
        assert r.json() == {"detail": "choose_role"}


def test_role_admin_rejected(client_without_profile):
    r = client_without_profile.post("/api/me/role", json={"role": "admin", "display_name": "Eve"})
    assert r.status_code == 422


def test_role_second_time_conflicts(client):
    r = client.post("/api/me/role", json={"role": "client", "display_name": "Asha"})
    assert r.status_code == 409


@pytest.mark.parametrize("date", ["2026-02-30", "nope", "20261031"])
def test_impossible_date_is_400(client, date):
    r = client.get(f"/api/meals?date={date}")
    assert r.status_code == 400
    assert r.json()["detail"] == "date must be a real YYYY-MM-DD date"


@pytest.mark.parametrize("bad", ["2026-02-30T08:00", "yesterday", "2026-10-31T08:00:00", "2026-1-3T8:0", "2026-10-31T8:15"])
def test_malformed_eaten_at_is_422(client, bad):
    assert client.post("/api/meals", json={**MEAL, "eaten_at": bad}).status_code == 422


def test_canonical_eaten_at_is_accepted(client):
    assert client.post("/api/meals", json={**MEAL, "eaten_at": "2026-10-31T08:15"}).status_code == 201


def test_delete_missing_meal_is_404(client_store_down):
    c = make_client(FakeStore(profile=dict(PROFILE), delete_result=False))
    assert c.delete("/api/meals/99").status_code == 404


def test_delete_meal_is_204(client):
    assert client.delete("/api/meals/1").status_code == 204


def test_store_unavailable_is_503(client_store_down):
    r = client_store_down.get("/api/meals?date=2026-10-31")
    assert r.status_code == 503
    assert r.json() == {"detail": "The database is unreachable. Try again in a minute."}


def test_daylog_totals_unchanged(client):
    assert client.post("/api/meals", json=MEAL).status_code == 201
    assert client.post("/api/meals", json={**MEAL, "items": [ITEM, ITEM2]}).status_code == 201
    log = client.get("/api/meals?date=2026-10-31").json()
    assert len(log["meals"]) == 2
    assert log["total_calories"] == round(150 + 150 + 200)
    assert log["protein_g"] == round(8.25 * 2 + 4.0, 1)
    assert log["carbs_g"] == round(20.1 * 2 + 44.0, 1)
    assert log["fat_g"] == round(3.04 * 2 + 0.5, 1)
