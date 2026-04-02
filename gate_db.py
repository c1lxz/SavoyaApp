from __future__ import annotations

import json
import os
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
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
WIEGAND_BITS = 26


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


def _table_exists(cursor: pyodbc.Cursor, name: str) -> bool:
    row = cursor.tables(table=name, tableType="TABLE").fetchone()
    return row is not None


def _ensure_wiegand_schema(cursor: pyodbc.Cursor) -> None:
    if _table_exists(cursor, "WiegandCredentials"):
        return

    cursor.execute(
        """
        CREATE TABLE WiegandCredentials (
            id AUTOINCREMENT PRIMARY KEY,
            key_id INTEGER,
            user_id INTEGER,
            access_point_id INTEGER,
            bit_length INTEGER,
            facility_code INTEGER,
            card_number INTEGER,
            wiegand_payload TEXT(16),
            created_at DATETIME
        )
        """
    )
    cursor.execute("CREATE UNIQUE INDEX idx_wiegand_key_access ON WiegandCredentials (key_id, access_point_id)")


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


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


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


def _parity_bit_even(value: int) -> int:
    return bin(value).count("1") % 2


def _parity_bit_odd(value: int) -> int:
    return 1 - (bin(value).count("1") % 2)


def _encode_wiegand26(facility_code: int, card_number: int) -> str:
    if not (0 <= facility_code <= 255):
        raise ValueError("facility_code must be in [0, 255]")
    if not (0 <= card_number <= 65535):
        raise ValueError("card_number must be in [0, 65535]")

    data24 = (facility_code << 16) | card_number
    high12 = (data24 >> 12) & 0xFFF
    low12 = data24 & 0xFFF

    parity_even = _parity_bit_even(high12)
    parity_odd = _parity_bit_odd(low12)

    frame26 = (parity_even << 25) | (data24 << 1) | parity_odd
    return f"{frame26:07X}"


def _next_wiegand_values(key_id: int, user_id: int, access_point_id: int, probe: int = 0) -> tuple[int, int]:
    facility_code = ((user_id * 17 + access_point_id * 31 + key_id + probe) % 255) + 1
    card_number = ((key_id * 131 + user_id * 19 + access_point_id * 997 + probe) % 65535) + 1
    return facility_code, card_number


def _find_wiegand_for_key(cursor: pyodbc.Cursor, key_id: int, access_point_id: int) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT id, bit_length, facility_code, card_number, wiegand_payload
        FROM WiegandCredentials
        WHERE key_id = ? AND access_point_id = ?
        """,
        (key_id, access_point_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None

    return {
        "id": int(row.id),
        "bit_length": int(row.bit_length),
        "facility_code": int(row.facility_code),
        "card_number": int(row.card_number),
        "wiegand_payload": str(row.wiegand_payload),
    }


def _wiegand_pair_in_use(cursor: pyodbc.Cursor, facility_code: int, card_number: int, exclude_id: int | None = None) -> bool:
    if exclude_id is None:
        cursor.execute(
            """
            SELECT TOP 1 id
            FROM WiegandCredentials
            WHERE facility_code = ? AND card_number = ?
            """,
            (facility_code, card_number),
        )
    else:
        cursor.execute(
            """
            SELECT TOP 1 id
            FROM WiegandCredentials
            WHERE facility_code = ? AND card_number = ? AND id <> ?
            """,
            (facility_code, card_number, exclude_id),
        )
    return cursor.fetchone() is not None


def _create_wiegand_credential(cursor: pyodbc.Cursor, key_id: int, user_id: int, access_point_id: int) -> dict[str, Any]:
    probe = 0
    while probe < 2048:
        facility_code, card_number = _next_wiegand_values(key_id=key_id, user_id=user_id, access_point_id=access_point_id, probe=probe)
        if not _wiegand_pair_in_use(cursor, facility_code, card_number):
            payload = _encode_wiegand26(facility_code, card_number)
            cursor.execute(
                """
                INSERT INTO WiegandCredentials
                (key_id, user_id, access_point_id, bit_length, facility_code, card_number, wiegand_payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (key_id, user_id, access_point_id, WIEGAND_BITS, facility_code, card_number, payload, datetime.now()),
            )
            return {
                "bit_length": WIEGAND_BITS,
                "facility_code": facility_code,
                "card_number": card_number,
                "wiegand_payload": payload,
            }
        probe += 1

    raise RuntimeError("Failed to allocate unique Wiegand-26 credential")


def _get_or_create_wiegand_credential(cursor: pyodbc.Cursor, key_id: int, user_id: int, access_point_id: int) -> dict[str, Any]:
    existing = _find_wiegand_for_key(cursor, key_id=key_id, access_point_id=access_point_id)
    if existing is not None:
        return existing
    return _create_wiegand_credential(cursor, key_id=key_id, user_id=user_id, access_point_id=access_point_id)


def _ensure_wiegand_credentials_for_points(cursor: pyodbc.Cursor, key_id: int, user_id: int, access_point_ids: list[int]) -> None:
    for access_point_id in access_point_ids:
        _get_or_create_wiegand_credential(cursor, key_id=key_id, user_id=user_id, access_point_id=access_point_id)


def _all_access_point_ids(cursor: pyodbc.Cursor) -> list[int]:
    cursor.execute("SELECT id FROM AccessPoints ORDER BY id")
    rows = cursor.fetchall()
    return [int(row.id) for row in rows]


def add_permanent_key(
    key_type: str,
    key_value: str,
    access_point_ids: list[int],
    resident_name: str = "Resident",
) -> int:
    validated_key_type = _validate_key_type(key_type)
    normalized_key_value = _normalize_key_value(validated_key_type, key_value)
    validated_points = _validate_access_point_ids(access_point_ids)

    with _transaction_cursor() as (_, cursor):
        _ensure_wiegand_schema(cursor)

        existing = _find_existing_active_key(cursor, validated_key_type, normalized_key_value)
        if existing is not None:
            key_id, user_id, _ = existing
            _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=True)
            _ensure_wiegand_credentials_for_points(
                cursor,
                key_id=key_id,
                user_id=user_id,
                access_point_ids=_all_access_point_ids(cursor),
            )
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
        _ensure_wiegand_credentials_for_points(
            cursor,
            key_id=key_id,
            user_id=user_id,
            access_point_ids=_all_access_point_ids(cursor),
        )
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
    normalized_expires_at = _to_naive_utc(expires_at)
    if normalized_expires_at <= datetime.utcnow():
        raise ValueError("expires_at must be in the future")

    with _transaction_cursor() as (_, cursor):
        _ensure_wiegand_schema(cursor)

        existing = _find_existing_active_key(cursor, validated_key_type, normalized_key_value)
        if existing is not None:
            key_id, user_id, current_valid_to = existing
            if current_valid_to is None:
                _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=True)
                _ensure_wiegand_credentials_for_points(
                    cursor,
                    key_id=key_id,
                    user_id=user_id,
                    access_point_ids=_all_access_point_ids(cursor),
                )
                return key_id

            if normalized_expires_at > _to_naive_utc(current_valid_to):
                cursor.execute("UPDATE Keys SET valid_to = ? WHERE id = ?", (normalized_expires_at, key_id))

            _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=False)
            _ensure_wiegand_credentials_for_points(
                cursor,
                key_id=key_id,
                user_id=user_id,
                access_point_ids=_all_access_point_ids(cursor),
            )
            return key_id

        user_id = _create_user(cursor, normalized_key_value, is_visitor=True)
        key_id = _create_key(
            cursor=cursor,
            user_id=user_id,
            key_type=validated_key_type,
            key_value=normalized_key_value,
            valid_from=datetime.now(),
            valid_to=normalized_expires_at,
        )
        _add_missing_access_permissions(cursor, user_id, validated_points, is_permanent=False)
        _ensure_wiegand_credentials_for_points(
            cursor,
            key_id=key_id,
            user_id=user_id,
            access_point_ids=_all_access_point_ids(cursor),
        )
        return key_id


def remove_key(key_id: int) -> bool:
    if not isinstance(key_id, int) or key_id <= 0:
        raise ValueError("key_id must be a positive integer")

    with _transaction_cursor() as (_, cursor):
        _ensure_wiegand_schema(cursor)

        cursor.execute("SELECT user_id, valid_to FROM Keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        if row is None:
            return False

        user_id = int(row.user_id)

        cursor.execute("DELETE FROM WiegandCredentials WHERE key_id = ?", (key_id,))
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
    check_time = _to_naive_utc(now) if now is not None else datetime.now()
    if not isinstance(check_time, datetime):
        raise ValueError("now must be datetime or None")

    with _transaction_cursor() as (_, cursor):
        _ensure_wiegand_schema(cursor)

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
        cursor.execute(f"DELETE FROM WiegandCredentials WHERE key_id IN ({placeholders})", expired_key_ids)
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


def _send_wiegand26(access_point_id: int, credential: dict[str, Any]) -> GateOpenResponse:
    transport = os.getenv("GATE_WIEGAND_TRANSPORT", "dry_run").strip().lower()
    timeout_seconds = float(os.getenv("GATE_WIEGAND_TIMEOUT_SECONDS", "2.0"))

    payload = {
        "access_point_id": access_point_id,
        "wiegand": {
            "bit_length": WIEGAND_BITS,
            "facility_code": credential["facility_code"],
            "card_number": credential["card_number"],
            "payload_hex": credential["wiegand_payload"],
        },
    }

    if transport in {"", "dry_run", "mock", "simulate", "disabled"}:
        return GateOpenResponse(
            success=True,
            message=(
                f"Wiegand-26 dry-run sent: AP={access_point_id}, FC={credential['facility_code']}, "
                f"CN={credential['card_number']}, HEX={credential['wiegand_payload']}"
            ),
        )

    if transport in {"tcp", "tcp_ip", "socket"}:
        host = os.getenv("GATE_WIEGAND_TCP_HOST", "").strip()
        raw_port = os.getenv("GATE_WIEGAND_TCP_PORT", "").strip()
        if not host:
            return GateOpenResponse(
                success=False,
                error_code="integration_unavailable",
                message="GATE_WIEGAND_TCP_HOST is not configured",
            )
        if not raw_port:
            return GateOpenResponse(
                success=False,
                error_code="integration_unavailable",
                message="GATE_WIEGAND_TCP_PORT is not configured",
            )

        try:
            port = int(raw_port)
        except ValueError:
            return GateOpenResponse(
                success=False,
                error_code="integration_unavailable",
                message=f"Invalid GATE_WIEGAND_TCP_PORT: {raw_port}",
            )

        payload_format = os.getenv("GATE_WIEGAND_TCP_PAYLOAD_FORMAT", "json").strip().lower()
        if payload_format == "json":
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        elif payload_format in {"payload_hex", "hex"}:
            body = str(credential["wiegand_payload"])
        elif payload_format in {"fc_cn", "facility_card"}:
            body = f"{credential['facility_code']}:{credential['card_number']}"
        else:
            return GateOpenResponse(
                success=False,
                error_code="transport_not_supported",
                message=f"Unknown GATE_WIEGAND_TCP_PAYLOAD_FORMAT: {payload_format}",
            )

        append_newline = os.getenv("GATE_WIEGAND_TCP_APPEND_NEWLINE", "true").strip().lower() in {"1", "true", "yes", "on"}
        encoding = os.getenv("GATE_WIEGAND_TCP_ENCODING", "utf-8").strip() or "utf-8"
        wire_data = (body + ("\n" if append_newline else "")).encode(encoding)

        try:
            with socket.create_connection((host, port), timeout=timeout_seconds) as conn:
                conn.sendall(wire_data)
            return GateOpenResponse(
                success=True,
                message=f"Wiegand-26 sent via TCP to {host}:{port}",
            )
        except Exception as exc:
            return GateOpenResponse(
                success=False,
                error_code="transport_error",
                message=f"Wiegand TCP transport failed: {exc}",
            )

    if transport != "http":
        return GateOpenResponse(success=False, error_code="transport_not_supported", message=f"Unknown transport: {transport}")

    url = os.getenv("GATE_WIEGAND_HTTP_URL", "").strip()
    if not url:
        return GateOpenResponse(
            success=False,
            error_code="integration_unavailable",
            message="GATE_WIEGAND_HTTP_URL is not configured",
        )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = os.getenv("GATE_WIEGAND_HTTP_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout_seconds)
        if response.status_code >= 400:
            return GateOpenResponse(
                success=False,
                error_code="transport_http_error",
                message=f"Wiegand transport HTTP {response.status_code}",
            )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if isinstance(data, dict):
            success = bool(data.get("success", True))
            message = str(data.get("message") or "Wiegand-26 command accepted")
            error_code = str(data.get("error_code")) if data.get("error_code") else None
            return GateOpenResponse(success=success, message=message, error_code=error_code)

        return GateOpenResponse(success=True, message="Wiegand-26 command accepted")
    except Exception as exc:
        return GateOpenResponse(success=False, error_code="transport_error", message=f"Wiegand transport failed: {exc}")


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


def get_wiegand_credentials(external_key_id: str) -> list[dict[str, Any]]:
    with _transaction_cursor() as (_, cursor):
        _ensure_wiegand_schema(cursor)

        key_id = _resolve_active_key_id(cursor, external_key_id)
        if key_id is None:
            return []

        cursor.execute(
            """
            SELECT wc.access_point_id, wc.bit_length, wc.facility_code, wc.card_number, wc.wiegand_payload
            FROM WiegandCredentials wc
            WHERE wc.key_id = ?
            ORDER BY wc.access_point_id
            """,
            (key_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "access_point_id": int(row.access_point_id),
                "bit_length": int(row.bit_length),
                "facility_code": int(row.facility_code),
                "card_number": int(row.card_number),
                "payload_hex": str(row.wiegand_payload),
            }
            for row in rows
        ]


def open_access_point(access_point_id: int, external_key_id: str | None = None) -> dict[str, Any]:
    if not isinstance(access_point_id, int) or access_point_id <= 0:
        raise ValueError("access_point_id must be a positive integer")

    with _transaction_cursor() as (_, cursor):
        _ensure_wiegand_schema(cursor)

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

        if key_id is None:
            result = GateOpenResponse(
                success=False,
                error_code="key_not_found",
                message="Open by key requires external_key_id",
            )
            return {"success": result.success, "error_code": result.error_code, "message": result.message}

        cursor.execute("SELECT user_id FROM Keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        if row is None:
            result = GateOpenResponse(success=False, error_code="key_not_found", message="Key was removed")
            return {"success": result.success, "error_code": result.error_code, "message": result.message}

        user_id = int(row.user_id)
        credential = _get_or_create_wiegand_credential(
            cursor,
            key_id=key_id,
            user_id=user_id,
            access_point_id=access_point_id,
        )

        transport_result = _send_wiegand26(access_point_id=access_point_id, credential=credential)
        return {
            "success": transport_result.success,
            "error_code": transport_result.error_code,
            "message": transport_result.message,
        }
