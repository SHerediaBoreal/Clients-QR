from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _load_buenos_aires_tz():
    try:
        return ZoneInfo("America/Argentina/Buenos_Aires")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-3), name="America/Argentina/Buenos_Aires")


BUENOS_AIRES_TZ = _load_buenos_aires_tz()


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def now_buenos_aires() -> datetime:
    return datetime.now(BUENOS_AIRES_TZ)


def to_buenos_aires(value: datetime) -> datetime:
    return ensure_aware_utc(value).astimezone(BUENOS_AIRES_TZ)


def start_of_day_utc(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=BUENOS_AIRES_TZ).astimezone(UTC)


def end_of_day_utc(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=BUENOS_AIRES_TZ).astimezone(UTC)
