import datetime

from app.checkin_rules import CHECKIN_DAYS, is_due, next_due_on

D = datetime.date


def test_no_checkin_is_due_today():
    assert CHECKIN_DAYS == 7
    assert next_due_on(None, D(2026, 10, 31)) == D(2026, 10, 31)
    assert is_due(None, D(2026, 10, 31)) is True


def test_seven_days_ago_is_due():
    last = D(2026, 10, 24)
    assert next_due_on(last, D(2026, 10, 31)) == D(2026, 10, 31)
    assert is_due(last, D(2026, 10, 31)) is True


def test_six_days_ago_not_due():
    last = D(2026, 10, 25)
    assert next_due_on(last, D(2026, 10, 31)) == D(2026, 11, 1)
    assert is_due(last, D(2026, 10, 31)) is False
