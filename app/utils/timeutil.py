"""All timestamps in the DB are naive local time in settings.TIMEZONE (Asia/Karachi
by default) so that "today's applications" means today in Lahore even when the
server runs in UTC on Render."""
from datetime import datetime, date, timedelta

from app.config import settings


def now() -> datetime:
    return datetime.now(settings.tz).replace(tzinfo=None)


def today() -> date:
    return now().date()


def start_of_today() -> datetime:
    return datetime.combine(today(), datetime.min.time())


def start_of_month() -> datetime:
    t = today()
    return datetime(t.year, t.month, 1)


def start_of_year() -> datetime:
    return datetime(today().year, 1, 1)


def days_ago(n: int) -> datetime:
    return start_of_today() - timedelta(days=n)
