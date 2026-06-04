from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone


GMT_MINUS_3_TZ = timezone(timedelta(hours=-3), name="GMT-3")
# Alias kept for backwards compatibility with the rest of the codebase.
BUENOS_AIRES_TZ = GMT_MINUS_3_TZ


def ensure_aware_gmt_minus_3(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=GMT_MINUS_3_TZ)
    return value.astimezone(GMT_MINUS_3_TZ)


def ensure_aware_utc(value: datetime) -> datetime:
    return ensure_aware_gmt_minus_3(value).astimezone(UTC)


def now_buenos_aires() -> datetime:
    return datetime.now(GMT_MINUS_3_TZ)


def to_buenos_aires(value: datetime) -> datetime:
    return ensure_aware_gmt_minus_3(value)


def start_of_day_utc(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=GMT_MINUS_3_TZ).astimezone(UTC)


def end_of_day_utc(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=GMT_MINUS_3_TZ).astimezone(UTC)
