from datetime import date, datetime, timezone

import pytest

from app.reminders import should_remind, yangon_today

TODAY = date(2026, 11, 7)


def test_not_due_never_reminds():
    assert should_remind(False, 0, None, TODAY) is False


def test_due_first_reminder():
    assert should_remind(True, 0, None, TODAY) is True


@pytest.mark.parametrize("days_ago,expected", [(0, False), (2, False), (3, True), (10, True)])
def test_second_reminder_needs_three_days(days_ago, expected):
    last = date.fromordinal(TODAY.toordinal() - days_ago)
    assert should_remind(True, 1, last, TODAY) is expected


def test_second_reminder_without_last_date_is_allowed():
    assert should_remind(True, 1, None, TODAY) is True


@pytest.mark.parametrize("sent", [2, 3])
def test_never_more_than_two(sent):
    assert should_remind(True, sent, date(2026, 1, 1), TODAY) is False


def test_yangon_today_is_utc_plus_630():
    assert yangon_today(datetime(2026, 11, 7, 2, 30, tzinfo=timezone.utc)) == date(2026, 11, 7)
    assert yangon_today(datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)) == date(2026, 11, 7)
    assert yangon_today(datetime(2026, 11, 6, 17, 29, tzinfo=timezone.utc)) == date(2026, 11, 6)
