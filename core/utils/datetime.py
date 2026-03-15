from datetime import datetime, timezone

import pytz


def utcnow() -> datetime:
    """Return current UTC datetime with timezone info."""
    return datetime.now(tz=timezone.utc)


def localize(dt: datetime, tz_name: str) -> datetime:
    """Localize a naive or UTC datetime to the given timezone."""
    tz = pytz.timezone(tz_name)
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)


def format_date_hint(dt: datetime | None) -> str | None:
    """Format a datetime to a human-readable date hint."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d")
