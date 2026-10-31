"""M2 store methods against the local Supabase stack, acting as real users."""
import pytest

from app.auth import User
from app.schemas import SettingsIn
from app.store import SettingsExist, Store

pytestmark = pytest.mark.integration


def _store(u) -> Store:
    return Store(User(id=u.id, token=u.token))


def test_settings_upsert_and_only_if_empty(make_user, service):
    u = make_user()
    s = _store(u)
    assert s.get_settings() is None
    first = s.put_settings(SettingsIn(weight_kg=70.55, activity=1.375, goal_kcal=1800))
    assert first["activity"] == 1.375 and first["weight_kg"] == 70.55
    assert first["goal_set_by"] == u.id
    second = s.put_settings(SettingsIn(weight_kg=69, activity=1.55, goal_kcal=1800,
                                       weight_unit="lb", reminders_enabled=True))
    assert second["weight_kg"] == 69 and second["activity"] == 1.55
    assert second["weight_unit"] == "lb" and second["reminders_enabled"] is True
    assert s.get_settings()["weight_kg"] == 69
    with pytest.raises(SettingsExist):
        s.put_settings(SettingsIn(weight_kg=50), only_if_empty=True)
    assert s.get_settings()["weight_kg"] == 69
    # daily-job columns are never overwritten by a user save
    service.patch("/client_settings", params={"user_id": f"eq.{u.id}"},
                  json={"reminders_sent": 2, "last_reminded_on": "2026-10-30"})
    s.put_settings(SettingsIn(weight_kg=68))
    row = service.get("/client_settings", params={"user_id": f"eq.{u.id}"}).json()[0]
    assert row["reminders_sent"] == 2 and row["last_reminded_on"] == "2026-10-30"


def test_only_if_empty_inserts_when_no_row(make_user):
    u = make_user()
    out = _store(u).put_settings(SettingsIn(weight_kg=80), only_if_empty=True)
    assert out["weight_kg"] == 80


def test_weight_upsert_replaces_same_day_and_updates_settings(make_user, service):
    import datetime
    u = make_user()
    s = _store(u)
    s.put_settings(SettingsIn(weight_kg=60, goal_kcal=1800))
    service.patch("/client_settings", params={"user_id": f"eq.{u.id}"},
                  json={"reminders_sent": 1, "last_reminded_on": "2026-10-30"})
    day = datetime.date(2026, 10, 31)
    s.upsert_weight(day, 70.0)
    out = s.upsert_weight(day, 71.25)
    assert out.weight_kg == 71.25 and out.logged_on == "2026-10-31"
    rows = s.weights_between(day, day)
    assert [(r.logged_on, r.weight_kg) for r in rows] == [("2026-10-31", 71.25)]
    st = s.get_settings()
    assert st["weight_kg"] == 71.25
    assert st["goal_kcal"] == 1800 and st["goal_set_by"] == u.id
    assert st["reminders_sent"] == 1 and st["last_reminded_on"] == "2026-10-30"
    assert s.delete_weight(day) is True
    assert s.delete_weight(day) is False
    assert s.weights_between(day, day) == []


def test_weight_upsert_creates_settings_row_if_missing(make_user):
    import datetime
    s = _store(make_user())
    assert s.get_settings() is None
    s.upsert_weight(datetime.date(2026, 10, 31), 65.5)
    assert s.get_settings()["weight_kg"] == 65.5
