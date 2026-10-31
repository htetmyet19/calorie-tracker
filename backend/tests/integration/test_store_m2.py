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


def test_only_if_empty_fills_row_created_by_weight_log(make_user):
    # Ruling R7: a row that exists only because of a weight log has no saved
    # calculator values, so the one-time browser move fills it in.
    import datetime
    u = make_user()
    s = _store(u)
    s.upsert_weight(datetime.date(2026, 10, 31), 71.25)
    out = s.put_settings(SettingsIn(height_cm=170, age=30, sex="female", activity=1.375,
                                    weight_goal="lose", goal_kcal=1800), only_if_empty=True)
    assert out["goal_kcal"] == 1800 and out["activity"] == 1.375 and out["sex"] == "female"
    assert out["goal_set_by"] == u.id
    assert out["weight_kg"] == 71.25  # the logged weight is kept
    with pytest.raises(SettingsExist):
        s.put_settings(SettingsIn(goal_kcal=2500), only_if_empty=True)
    assert s.get_settings()["goal_kcal"] == 1800


def test_only_if_empty_keeps_reminders_of_a_push_subscriber(make_user):
    u = make_user()
    s = _store(u)
    s.add_push_subscription(f"https://push.example/{u.id}", "p256dh-key", "auth-key")
    out = s.put_settings(SettingsIn(goal_kcal=1900), only_if_empty=True)
    assert out["goal_kcal"] == 1900 and out["reminders_enabled"] is True


def test_backdated_weight_does_not_overwrite_profile_weight(make_user):
    import datetime
    s = _store(make_user())
    today = datetime.date(2026, 10, 31)
    s.upsert_weight(today, 80)
    s.upsert_weight(today - datetime.timedelta(days=30), 85)
    assert s.get_settings()["weight_kg"] == 80
    assert s.delete_weight(today) is True
    assert s.get_settings()["weight_kg"] == 85
    # the last log gone: the profile weight stays as it was
    assert s.delete_weight(today - datetime.timedelta(days=30)) is True
    assert s.get_settings()["weight_kg"] == 85


def test_goal_weight_saved_and_kept_when_weight_is_logged(make_user, service):
    import datetime
    u = make_user()
    s = _store(u)
    out = s.put_settings(SettingsIn(weight_kg=74, goal_kcal=1800, goal_weight_kg=74.05))
    assert out["goal_weight_kg"] == 74.05
    s.upsert_weight(datetime.date(2026, 10, 31), 71.5)
    st = s.get_settings()
    assert st["weight_kg"] == 71.5 and st["goal_weight_kg"] == 74.05  # the goal's basis stays
    r = service.patch("/client_settings", params={"user_id": f"eq.{u.id}"},
                      json={"goal_weight_kg": 29})
    assert r.status_code == 400  # check constraint


def test_goal_weight_filled_with_only_if_empty(make_user):
    import datetime
    s = _store(make_user())
    s.upsert_weight(datetime.date(2026, 10, 31), 65.5)  # row exists, nothing saved yet
    out = s.put_settings(SettingsIn(goal_kcal=1700, goal_weight_kg=65.5), only_if_empty=True)
    assert out["goal_kcal"] == 1700 and out["goal_weight_kg"] == 65.5
