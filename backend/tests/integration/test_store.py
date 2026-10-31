"""Store against the local Supabase stack, acting as real users (RLS applies)."""
import datetime

import pytest

from app import config
from app.auth import User
from app.schemas import FoodItem, MealIn
from app.store import ProfileExists, Store, StoreUnavailable

pytestmark = pytest.mark.integration


def _store(u) -> Store:
    return Store(User(id=u.id, token=u.token))


def _meal(eaten_at="2026-10-31T08:15", cal=300.0) -> MealIn:
    return MealIn(eaten_at=eaten_at, meal_type="breakfast",
                  items=[FoodItem(name="oats", portion="1 bowl", grams=80, calories=cal,
                                    protein_g=10, carbs_g=50, fat_g=6, confidence="high")])


def test_add_and_list_meal_roundtrip(make_user):
    s = _store(make_user())
    added = s.add_meal(_meal())
    assert added.eaten_at == "2026-10-31T08:15"
    assert added.total_calories == 300
    got = s.meals_on(datetime.date(2026, 10, 31))
    assert [m.model_dump() for m in got] == [added.model_dump()]


def test_meals_on_excludes_other_days(make_user):
    s = _store(make_user())
    s.add_meal(_meal("2026-10-30T23:59"))
    s.add_meal(_meal("2026-10-31T00:00"))
    s.add_meal(_meal("2026-11-01T00:00"))
    got = s.meals_on(datetime.date(2026, 10, 31))
    assert [m.eaten_at for m in got] == ["2026-10-31T00:00"]


def test_meals_on_orders_by_eaten_at(make_user):
    s = _store(make_user())
    s.add_meal(_meal("2026-10-31T19:00"))
    s.add_meal(_meal("2026-10-31T07:00"))
    got = s.meals_on(datetime.date(2026, 10, 31))
    assert [m.eaten_at for m in got] == ["2026-10-31T07:00", "2026-10-31T19:00"]


def test_trainer_meals_on_excludes_clients_meals(make_user, link):
    trainer, client = make_user("trainer"), make_user("client")
    link(client, trainer, "active")
    _store(client).add_meal(_meal())
    mine = _store(trainer).add_meal(_meal("2026-10-31T09:00"))
    got = _store(trainer).meals_on(datetime.date(2026, 10, 31))
    assert [m.id for m in got] == [mine.id]


def test_delete_own_meal(make_user):
    s = _store(make_user())
    m = s.add_meal(_meal())
    assert s.delete_meal_returning(m.id)["id"] == m.id
    assert s.meals_on(datetime.date(2026, 10, 31)) == []
    assert s.delete_meal_returning(m.id) is None


def test_delete_other_users_meal_returns_false(make_user, add_meal):
    owner, other = make_user(), make_user()
    row = add_meal(owner)
    assert _store(other).delete_meal_returning(row["id"]) is None
    assert _store(owner).delete_meal_returning(row["id"])["id"] == row["id"]


def test_trainer_cannot_delete_clients_meal(make_user, link, add_meal):
    trainer, client = make_user("trainer"), make_user("client")
    link(client, trainer, "active")
    row = add_meal(client)
    assert _store(trainer).delete_meal_returning(row["id"]) is None
    assert _store(client).delete_meal_returning(row["id"])["id"] == row["id"]


def test_get_and_create_profile(make_user):
    u = make_user(None)
    s = _store(u)
    assert s.get_profile() is None
    created = s.create_profile("client", "Asha")
    assert created["id"] == u.id and created["role"] == "client"
    assert created["display_name"] == "Asha"
    assert s.get_profile()["id"] == u.id


def test_create_profile_twice_raises_profile_exists(make_user):
    s = _store(make_user(None))
    s.create_profile("client", "A")
    with pytest.raises(ProfileExists):
        s.create_profile("client", "A")


def test_create_admin_profile_is_denied_without_leaking_body(make_user):
    s = _store(make_user(None))
    with pytest.raises(RuntimeError) as e:
        s.create_profile("admin", "x")
    assert str(e.value).startswith("Supabase returned 4")


def test_unreachable_supabase_raises_store_unavailable(make_user, monkeypatch):
    s = _store(make_user())
    monkeypatch.setattr(config, "SUPABASE_URL", "http://127.0.0.1:9")
    with pytest.raises(StoreUnavailable):
        s.get_profile()
