"""Weight log routes with fake auth and a fake Store; no network."""
import pytest
from fastapi.testclient import TestClient

from app.auth import User, current_user
from app.main import app
from app.schemas import WeightOut
from app.store import get_store
from tests.test_api import ITEM, PROFILE, FakeStore


class WeightStore(FakeStore):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.weights = {}

    def weights_between(self, start, end):
        return [WeightOut(logged_on=d.isoformat(), weight_kg=kg)
                for d, kg in sorted(self.weights.items()) if start <= d <= end]

    def upsert_weight(self, day, kg):
        self.weights[day] = round(kg, 2)
        return WeightOut(logged_on=day.isoformat(), weight_kg=self.weights[day])

    def delete_weight(self, day):
        return self.weights.pop(day, None) is not None


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    store = WeightStore(profile=dict(PROFILE))
    app.dependency_overrides[current_user] = lambda: User(id="u1", token="t")
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def test_put_weight_roundtrip(client):
    r = client.put("/api/weights/2026-10-31", json={"weight_kg": 70.256})
    assert r.status_code == 200
    assert r.json() == {"logged_on": "2026-10-31", "weight_kg": 70.26}
    client.put("/api/weights/2026-10-30", json={"weight_kg": 71})
    r = client.get("/api/weights", params={"from": "2026-10-01", "to": "2026-10-31"})
    assert r.status_code == 200
    assert r.json() == [{"logged_on": "2026-10-30", "weight_kg": 71.0},
                        {"logged_on": "2026-10-31", "weight_kg": 70.26}]
    assert client.delete("/api/weights/2026-10-31").status_code == 204


@pytest.mark.parametrize("kg", [29.9, 300.1])
def test_weight_out_of_range_422(client, kg):
    assert client.put("/api/weights/2026-10-31", json={"weight_kg": kg}).status_code == 422


def test_weights_bad_dates_400(client):
    def get(f, t):
        return client.get("/api/weights", params={"from": f, "to": t})
    r = get("2026-02-30", "2026-03-05")
    assert r.status_code == 400 and r.json()["detail"] == "from must be a real YYYY-MM-DD date"
    r = get("2026-03-01", "2026-13-05")
    assert r.status_code == 400 and r.json()["detail"] == "to must be a real YYYY-MM-DD date"
    assert get("2026-03-05", "2026-03-01").status_code == 400
    assert get("2026-01-01", "2027-02-06").status_code == 400  # 401 days
    assert get("2026-01-01", "2027-02-05").status_code == 200  # 400 days
    assert client.put("/api/weights/2026-02-30", json={"weight_kg": 70}).status_code == 400
    assert client.delete("/api/weights/nope").status_code == 400


def test_delete_missing_weight_404(client):
    assert client.delete("/api/weights/2026-10-31").status_code == 404


def test_meals_date_still_validated(client):
    r = client.get("/api/meals", params={"date": "2026-02-30"})
    assert r.status_code == 400 and r.json()["detail"] == "date must be a real YYYY-MM-DD date"
    assert client.get("/api/meals", params={"date": "2026-10-31"}).status_code == 200
