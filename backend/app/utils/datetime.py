from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_isoformat(value: datetime | None) -> str | None:
    normalized = ensure_utc_datetime(value)
    return normalized.isoformat() if normalized is not None else None
