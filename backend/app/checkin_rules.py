import datetime

CHECKIN_DAYS = 7


def next_due_on(last: datetime.date | None, today: datetime.date) -> datetime.date:
    if last is None:
        return today
    return last + datetime.timedelta(days=CHECKIN_DAYS)


def is_due(last: datetime.date | None, today: datetime.date) -> bool:
    return today >= next_due_on(last, today)
