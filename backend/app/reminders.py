"""Pure reminder rules for the weekly check-in push."""
import datetime

REMINDER_GAP_DAYS = 3
MAX_REMINDERS = 2


# Asia/Yangon is UTC+06:30 all year (no daylight saving). A fixed offset needs no
# tz database, which serverless Python images may not ship.
YANGON = datetime.timezone(datetime.timedelta(hours=6, minutes=30))


def yangon_today(now_utc: datetime.datetime) -> datetime.date:
    """The calendar date in Asia/Yangon at the given (timezone-aware) instant."""
    return now_utc.astimezone(YANGON).date()


def should_remind(due: bool, sent: int, last_reminded_on: datetime.date | None,
                  today: datetime.date) -> bool:
    """At most 2 reminders per due check-in: the first when due, the second 3+ days later."""
    if not due or sent >= MAX_REMINDERS:
        return False
    if sent == 0:
        return True
    if last_reminded_on is None:
        return True
    return today >= last_reminded_on + datetime.timedelta(days=REMINDER_GAP_DAYS)
