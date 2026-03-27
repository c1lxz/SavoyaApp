from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyodbc

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent
_DEFAULT_MDB_PATH = _PROJECT_ROOT / "config.mdb"
ALLOWED_KEY_TYPES = {"Phone", "VehicleNumber"}


@dataclass
class GateOpenResponse:
    success: bool
    message: str
    error_code: str | None = None


def get_connection() -> pyodbc.Connection:
    raw_path = os.getenv("GATE_MDB_PATH", str(_DEFAULT_MDB_PATH))
    mdb_path = Path(raw_path)
    if not mdb_path.is_absolute():
        mdb_path = (_PROJECT_ROOT / mdb_path).resolve()
    if not mdb_path.exists():
        raise FileNotFoundError(f"GATE .mdb is not found: {mdb_path}")

    conn_str = f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={mdb_path}"
    return pyodbc.connect(conn_str)


@contextmanager
def _transaction_cursor():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield conn, cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def _validate_key_type(key_type: str) -> str:
    if key_type not in ALLOWED_KEY_TYPES:
        raise ValueError(f"Unsupported key_type: {key_type}. Allowed: {sorted(ALLOWED_KEY_TYPES)}")
    return key_type


def _normalize_key_value(key_type: str, key_value: str) -> str:
    if key_value is None:
        raise ValueError("key_value must not be None")

    value = key_value.strip()
    if not value:
        raise ValueError("key_value must not be empty")

    if key_type == "VehicleNumber":
        return "".join(value.upper().split())
    if key_type == "Phone":
        digits = "".join(ch for ch in value if ch.isdigit())
        if not digits:
            raise ValueError("Phone key_value must contain digits")
        return digits
    return value


def _validate_access_point_ids(access_point_ids: list[int]) -> list[int]:
    if not access_point_ids:
        raise ValueError("access_point_ids must not be empty")

    normalized: list[int] = []
    seen: set[int] = set()
    for point_id in access_point_ids:
        if not isinstance(point_id, int):
            raise ValueError("access_point_ids must contain integers")
        if point_id <= 0:
            raise ValueError("access_point_ids must contain positive integers")
        if point_id not in seen:
            seen.add(point_id)
            normalized.append(point_id)

    return normalized


def _create_user(cursor: pyodbc.Cursor, name: str, is_visitor: bool) -> int:
    safe_name = (name or "").strip() or "Unknown"
    now = datetime.now()
    cursor.execute(
        """
        INSERT INTO Users (last_name, first_name, is_visitor, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (safe_name, safe_name, 1 if is_visitor else 0, now),
    )
    return int(cursor.execute("SELECT @@IDENTITY").fetchval())


def _create_key(
    cursor: pyodbc.Cursor,
    user_id: int,
    key_type: str,
    key_value: str,
    valid_from: datetime,
    valid_to: datetime | None,
) -> int:
    cursor.execute(
        """
        INSERT INTO Keys (user_id, key_type, key_value, valid_from, valid_to, is_blocked)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (user_id, key_type, key_value, valid_from, valid_to),
    )
    return int(cursor.execute("SELECT @@IDENTITY").fetchval())


def _add_missing_access_permissions(
    cursor: pyodbc.Cursor,
    user_id: int,
    access_point_ids: list[int],
    is_permanent: bool,
) -> None:
    for ap_id in access_point_ids:
        cursor.execute(
            """
            SELECT id
            FROM AccessPermissions
            WHERE user_id = ? AND access_point_id = ?
            """,
            (user_id, ap_id),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO AccessPermissions (user_id, access_point_id, is_permanent)
                VALUES (?, ?, ?)
                """,
                (user_id, ap_id, 1 if is_permanent else 0),
            )


def _find_existing_active_key(
    cursor: pyodbc.Cursor, key_type: str, normalized_key_value: str
) -> tuple[int, int, datetime | None] | None:
    # Fast path: for normalized data this query is index-friendly and avoids full scans.
    cursor.execute(
        """
        SELECT id, user_id, valid_to
        FROM Keys
        WHERE key_type = ? AND key_value = ? AND is_blocked = 0
        """,
        (key_type, normalized_key_value),
    )
    direct_match = cursor.fetchone()
    if direct_match is not None:
        return int(direct_match.id), int(direct_match.user_id), direct_match.valid_to

    # Fallback for legacy non-normalized records. This path is slower but executed only
    # when direct lookup misses; found records are normalized in-place for next requests.
    cursor.execute(
        """
        SELECT id, user_id, valid_to, key_value
        FROM Keys
        WHERE key_type = ? AND is_blocked = 0
        """,
        (key_type,),
    )
    rows = cursor.fetchall()
    for row in rows:
        existing_normalized = _normalize_key_value(key_type, str(row.key_value))
        if existing_normalized == normalized_key_value:
            if str(row.key_value) != normalized_key_value:
                cursor.execute("UPDATE Keys SET key_value = ? WHERE id = ?", (normalized_key_value, int(row.id)))
            return int(row.id), int(row.user_id), row.valid_to
    return None


def add_permanent_key(
    key_type: str,
    key_value: str,
    access_point_ids: list[int],
    resident_name: str = "Житель",
) -> int:
    validated_key_type = _validate_key_type(key_type)
    normalized_key_value = _normalize_key_value(validated_key_type, key_value)
    validated_points = _validate_access_point_ids(access_point_ids)

    with _transaction_cursor() as (_, cursor):
        existing = _find_existing_active_key(cursor, validated_key_type, normalized_key_value)
        if existing is not None:
            key_id, user_id, _ = existing
            _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=True)
            return key_id

        user_id = _create_user(cursor, resident_name, is_visitor=False)
        key_id = _create_key(
            cursor=cursor,
            user_id=user_id,
            key_type=validated_key_type,
            key_value=normalized_key_value,
            valid_from=datetime.now(),
            valid_to=None,
        )
        _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=True)
        return key_id


def add_temporary_key(
    key_type: str,
    key_value: str,
    expires_at: datetime,
    access_point_ids: list[int],
) -> int:
    validated_key_type = _validate_key_type(key_type)
    normalized_key_value = _normalize_key_value(validated_key_type, key_value)
    validated_points = _validate_access_point_ids(access_point_ids)

    if not isinstance(expires_at, datetime):
        raise ValueError("expires_at must be a datetime instance")
    if expires_at <= datetime.now():
        raise ValueError("expires_at must be in the future")

    with _transaction_cursor() as (_, cursor):
        existing = _find_existing_active_key(cursor, validated_key_type, normalized_key_value)
        if existing is not None:
            key_id, user_id, current_valid_to = existing
            if current_valid_to is None:
                _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=True)
                return key_id

            if expires_at > current_valid_to:
                cursor.execute("UPDATE Keys SET valid_to = ? WHERE id = ?", (expires_at, key_id))

            _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=False)
            return key_id

        user_id = _create_user(cursor, normalized_key_value, is_visitor=True)
        key_id = _create_key(
            cursor=cursor,
            user_id=user_id,
            key_type=validated_key_type,
            key_value=normalized_key_value,
            valid_from=datetime.now(),
            valid_to=expires_at,
        )
        _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=False)
        return key_id


def remove_key(key_id: int) -> bool:
    if not isinstance(key_id, int) or key_id <= 0:
        raise ValueError("key_id must be a positive integer")

    with _transaction_cursor() as (_, cursor):
        cursor.execute("SELECT user_id, valid_to FROM Keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        if row is None:
            return False

        user_id = int(row.user_id)
        valid_to = row.valid_to
        if valid_to is None:
            return False

        cursor.execute("DELETE FROM Keys WHERE id = ?", (key_id,))
        deleted_rows = cursor.rowcount
        if deleted_rows <= 0:
            return False

        cursor.execute("SELECT COUNT(*) FROM Keys WHERE user_id = ?", (user_id,))
        has_other_keys = int(cursor.fetchone()[0]) > 0
        if not has_other_keys:
            cursor.execute("DELETE FROM AccessPermissions WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM Users WHERE id = ?", (user_id,))

        return True


def cleanup_expired_keys(now: datetime | None = None) -> int:
    check_time = now or datetime.now()
    if not isinstance(check_time, datetime):
        raise ValueError("now must be datetime or None")

    with _transaction_cursor() as (_, cursor):
        cursor.execute(
            """
            SELECT id, user_id
            FROM Keys
            WHERE valid_to IS NOT NULL AND valid_to < ?
            """,
            (check_time,),
        )
        expired_rows = cursor.fetchall()
        if not expired_rows:
            return 0

        expired_key_ids = [int(row.id) for row in expired_rows]
        user_ids = {int(row.user_id) for row in expired_rows}

        placeholders = ", ".join(["?"] * len(expired_key_ids))
        cursor.execute(f"DELETE FROM Keys WHERE id IN ({placeholders})", expired_key_ids)

        for user_id in user_ids:
            cursor.execute("SELECT COUNT(*) FROM Keys WHERE user_id = ?", (user_id,))
            has_other_keys = int(cursor.fetchone()[0]) > 0
            if not has_other_keys:
                cursor.execute("DELETE FROM AccessPermissions WHERE user_id = ?", (user_id,))
                cursor.execute("DELETE FROM Users WHERE id = ?", (user_id,))

        return len(expired_key_ids)


def get_access_points() -> list[dict[str, Any]]:
    with _transaction_cursor() as (_, cursor):
        cursor.execute("SELECT id, name FROM AccessPoints ORDER BY name")
        rows = cursor.fetchall()
        return [{"id": int(row.id), "name": str(row.name)} for row in rows]


def _access_point_exists(cursor: pyodbc.Cursor, access_point_id: int) -> bool:
    cursor.execute("SELECT id FROM AccessPoints WHERE id = ?", (access_point_id,))
    return cursor.fetchone() is not None


def _resolve_active_key_id(cursor: pyodbc.Cursor, external_key_id: str | None) -> int | None:
    if external_key_id is None:
        return None

    value = str(external_key_id).strip()
    if not value:
        return None

    if value.isdigit():
        cursor.execute("SELECT id FROM Keys WHERE id = ? AND is_blocked = 0", (int(value),))
        row = cursor.fetchone()
        if row is not None:
            return int(row.id)

    cursor.execute("SELECT id FROM Keys WHERE key_value = ? AND is_blocked = 0", (value,))
    row = cursor.fetchone()
    if row is None:
        return None
    return int(row.id)


def _has_key_permission(cursor: pyodbc.Cursor, key_id: int, access_point_id: int) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM AccessPermissions ap
        INNER JOIN Keys k ON k.user_id = ap.user_id
        WHERE ap.access_point_id = ?
          AND k.id = ?
        """,
        (access_point_id, key_id),
    )
    return cursor.fetchone() is not None


def get_key_permissions(external_key_id: str) -> list[dict[str, Any]]:
    with _transaction_cursor() as (_, cursor):
        key_id = _resolve_active_key_id(cursor, external_key_id)
        if key_id is None:
            return []

        cursor.execute(
            """
            SELECT ap.access_point_id, p.name
            FROM AccessPermissions ap
            INNER JOIN AccessPoints p ON p.id = ap.access_point_id
            INNER JOIN Keys k ON k.user_id = ap.user_id
            WHERE k.id = ?
            ORDER BY p.name
            """,
            (key_id,),
        )
        rows = cursor.fetchall()
        return [{"access_point_id": int(row.access_point_id), "access_point_name": str(row.name)} for row in rows]


def open_access_point(access_point_id: int, external_key_id: str | None = None) -> dict[str, Any]:
    if not isinstance(access_point_id, int) or access_point_id <= 0:
        raise ValueError("access_point_id must be a positive integer")

    with _transaction_cursor() as (_, cursor):
        if not _access_point_exists(cursor, access_point_id):
            result = GateOpenResponse(
                success=False,
                error_code="access_point_not_found",
                message="Access point not found in GATE database",
            )
            return {"success": result.success, "error_code": result.error_code, "message": result.message}

        key_id = _resolve_active_key_id(cursor, external_key_id)
        if external_key_id is not None and key_id is None:
            result = GateOpenResponse(
                success=False,
                error_code="key_not_found",
                message="Active key is not found in GATE database",
            )
            return {"success": result.success, "error_code": result.error_code, "message": result.message}

        if key_id is not None and not _has_key_permission(cursor, key_id, access_point_id):
            result = GateOpenResponse(
                success=False,
                error_code="access_denied",
                message="Key has no permission for access point",
            )
            return {"success": result.success, "error_code": result.error_code, "message": result.message}

        # HYPOTHESIS: actual physical open command is executed by a separate local service/SDK,
        # not by direct writes to GATE .mdb. This function defines a safe contract and returns
        # explicit integration_unavailable until confirmed transport is implemented.
        result = GateOpenResponse(
            success=False,
            error_code="integration_unavailable",
            message="Physical open transport is not configured",
        )
        return {"success": result.success, "error_code": result.error_code, "message": result.message}
