from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime


_phone_digits = re.compile(r"\D+")


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    cleaned = _phone_digits.sub("", raw)
    return cleaned or None


def hash_value(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_str(value: object | None) -> str:
    if value is None:
        return ""
    return str(value)

