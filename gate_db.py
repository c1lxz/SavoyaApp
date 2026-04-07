from __future__ import annotations

from datetime import datetime
from typing import Any


def _runtime():
    from backend.app.scripts import gate_runtime

    return gate_runtime


def get_connection():
    return _runtime().get_connection()


def add_permanent_key(
    key_type: str,
    key_value: str,
    access_point_ids: list[int],
    resident_name: str = "Resident",
) -> int:
    return _runtime().add_permanent_key(key_type, key_value, access_point_ids, resident_name)


def add_temporary_key(
    key_type: str,
    key_value: str,
    expires_at: datetime,
    access_point_ids: list[int],
) -> int:
    return _runtime().add_temporary_key(key_type, key_value, expires_at, access_point_ids)


def remove_key(key_id: int) -> bool:
    return _runtime().remove_key(key_id)


def cleanup_expired_keys(now: datetime | None = None) -> int:
    return _runtime().cleanup_expired_keys(now)


def get_access_points() -> list[dict[str, Any]]:
    return _runtime().get_access_points()


def get_key_permissions(external_key_id: str) -> list[dict[str, Any]]:
    return _runtime().get_key_permissions(external_key_id)


def get_wiegand_credentials(external_key_id: str) -> list[dict[str, Any]]:
    return _runtime().get_wiegand_credentials(external_key_id)


def open_access_point(access_point_id: int, external_key_id: str | None = None) -> dict[str, Any]:
    return _runtime().open_access_point(access_point_id, external_key_id)
