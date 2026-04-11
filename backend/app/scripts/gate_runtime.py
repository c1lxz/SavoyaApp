from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable

import pyodbc
from backend.app.services.gate_controller import GateController

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MDB_PATH = _PROJECT_ROOT / "config.mdb"
_DEFAULT_ODBC_DRIVER = "Driver do Microsoft Access (*.mdb)"
_REQUIRED_TABLES = {"Users", "Readers", "AccessTable"}
ALLOWED_KEY_TYPES = {"Phone", "VehicleNumber"}
WIEGAND_BITS = 26


@dataclass
class GateOpenResponse:
    success: bool
    message: str
    error_code: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class RealGateIdentity:
    number: str | None
    phone: str | None
    number_u: str
    number_mifare: str | None


def _env(name: str, *aliases: str, default: str | None = None, allow_empty: bool = False) -> str | None:
    for key in (name, *aliases):
        if key not in os.environ:
            continue
        value = os.environ[key]
        if value or allow_empty:
            return value
    return default


def _resolve_gate_paths() -> tuple[Path, Path]:
    raw_mdb = _env("GATE_MDB_PATH", default=str(_DEFAULT_MDB_PATH))
    raw_systemdb = _env("GATE_SYSTEMDB_PATH", "GATE_MDW_PATH")
    if not raw_mdb:
        raise RuntimeError("GATE_MDB_PATH is not set.")
    if not raw_systemdb:
        raise RuntimeError("GATE_SYSTEMDB_PATH is not set.")

    mdb_path = Path(raw_mdb)
    if not mdb_path.is_absolute():
        mdb_path = (_PROJECT_ROOT / mdb_path).resolve()
    systemdb_path = Path(raw_systemdb)
    if not systemdb_path.is_absolute():
        systemdb_path = (_PROJECT_ROOT / systemdb_path).resolve()

    if not mdb_path.exists():
        raise FileNotFoundError(f"GATE .mdb is not found: {mdb_path}")
    if not systemdb_path.exists():
        raise FileNotFoundError(f"Gate .mdw is not found: {systemdb_path}")

    return mdb_path, systemdb_path


def _resolve_gate_credentials() -> tuple[str, str]:
    uid = _env("GATE_MDB_UID", "GATE_UID")
    pwd = _env("GATE_MDB_PWD", "GATE_PWD", allow_empty=True)
    if not uid:
        raise RuntimeError("GATE_MDB_UID is not set.")
    if pwd is None:
        raise RuntimeError("GATE_MDB_PWD is not set.")
    return uid, pwd


def _pick_driver(preferred: str | None) -> str:
    candidates = [
        preferred,
        "Driver do Microsoft Access (*.mdb)",
        "Microsoft Access Driver (*.mdb)",
        "Microsoft Access-Treiber (*.mdb)",
    ]
    installed = {name.lower(): name for name in pyodbc.drivers()}
    for candidate in candidates:
        if candidate and candidate.lower() in installed:
            return installed[candidate.lower()]
    if preferred:
        return preferred
    raise RuntimeError("No compatible MDB ODBC driver was found.")


def _build_connection_string(mdb_path: Path, systemdb_path: Path) -> str:
    uid, pwd = _resolve_gate_credentials()
    preferred_driver = _env("GATE_ODBC_DRIVER", default=_DEFAULT_ODBC_DRIVER)
    driver = _pick_driver(preferred_driver)
    return f"DRIVER={{{driver}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"


def get_connection() -> pyodbc.Connection:
    mdb_path, systemdb_path = _resolve_gate_paths()
    return pyodbc.connect(_build_connection_string(mdb_path, systemdb_path))


@contextmanager
def _transaction_cursor():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_required_tables(cursor)
        yield conn, cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


@contextmanager
def _readonly_cursor():
    mdb_path, systemdb_path = _resolve_gate_paths()
    temp_dir = Path(tempfile.mkdtemp(prefix="gate-ro-"))
    temp_mdb = temp_dir / "config-copy.mdb"
    temp_systemdb = temp_dir / "Gate-copy.mdw"

    try:
        shutil.copy2(mdb_path, temp_mdb)
        shutil.copy2(systemdb_path, temp_systemdb)
        conn = pyodbc.connect(_build_connection_string(temp_mdb, temp_systemdb))
        cursor = conn.cursor()
        try:
            _ensure_required_tables(cursor)
            yield conn, cursor
        finally:
            cursor.close()
            conn.close()
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _list_tables(cursor: pyodbc.Cursor) -> set[str]:
    return {
        str(row.table_name)
        for row in cursor.tables()
        if str(getattr(row, "table_type", "")).upper() == "TABLE"
    }


def _ensure_required_tables(cursor: pyodbc.Cursor) -> None:
    tables = _list_tables(cursor)
    missing = sorted(_REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError(
            "Gate schema is not supported. Missing tables: "
            + ", ".join(missing)
            + ". Expected Users / Readers / AccessTable."
        )


def _validate_key_type(key_type: str) -> str:
    if key_type not in ALLOWED_KEY_TYPES:
        raise ValueError(f"Unsupported key_type: {key_type}. Allowed: {sorted(ALLOWED_KEY_TYPES)}")
    return key_type


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        raise ValueError("Phone key_value must contain digits")
    if digits.startswith("00"):
        return digits
    if digits.startswith("8") and len(digits) == 11:
        return f"007{digits[1:]}"
    if digits.startswith("7"):
        return f"00{digits}"
    return digits


def _normalize_vehicle(value: str) -> str:
    normalized = "".join((value or "").upper().split())
    if not normalized:
        raise ValueError("VehicleNumber key_value must not be empty")
    return normalized


def _normalize_key_value(key_type: str, key_value: str) -> str:
    if key_type == "Phone":
        return _normalize_phone(key_value)
    if key_type == "VehicleNumber":
        return _normalize_vehicle(key_value)
    raise ValueError(f"Unsupported key_type: {key_type}")


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


def _split_name(full_name: str) -> tuple[str | None, str | None, str | None]:
    parts = [part for part in (full_name or "").strip().split() if part]
    if not parts:
        return None, None, None
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], parts[1], None
    return parts[0], parts[1], " ".join(parts[2:])


def _generate_unique_number_u(cursor: pyodbc.Cursor) -> str:
    for _ in range(64):
        candidate = uuid.uuid4().hex[:12].upper()
        cursor.execute("SELECT TOP 1 UserPtr FROM Users WHERE NumberU = ?", (candidate,))
        if cursor.fetchone() is None:
            return candidate
    raise RuntimeError("Failed to generate a unique Users.NumberU value")


def _sample_key_type(cursor: pyodbc.Cursor, key_type: str) -> Any | None:
    env_name = "GATE_REAL_KEYTYPE_PHONE" if key_type == "Phone" else "GATE_REAL_KEYTYPE_VEHICLE"
    env_value = _env(env_name)
    if env_value is not None:
        try:
            return int(env_value)
        except ValueError:
            return env_value

    if key_type == "Phone":
        row = cursor.execute(
            """
            SELECT TOP 1 KeyType
            FROM Users
            WHERE (Deleted = 0 OR Deleted IS NULL)
              AND Phone IS NOT NULL
              AND Trim(Phone) <> ''
              AND KeyType IS NOT NULL
            ORDER BY UserPtr DESC
            """
        ).fetchone()
    else:
        row = cursor.execute(
            """
            SELECT TOP 1 KeyType
            FROM Users
            WHERE (Deleted = 0 OR Deleted IS NULL)
              AND Number IS NOT NULL
              AND Trim(Number) <> ''
              AND (Phone IS NULL OR Trim(Phone) = '')
              AND KeyType IS NOT NULL
            ORDER BY UserPtr DESC
            """
        ).fetchone()
    return row[0] if row is not None else None


def _sample_user_defaults(cursor: pyodbc.Cursor, key_type: str) -> dict[str, Any]:
    if key_type == "Phone":
        where_sql = """
            (Deleted = 0 OR Deleted IS NULL)
            AND Phone IS NOT NULL
            AND Trim(Phone) <> ''
        """
    else:
        where_sql = """
            (Deleted = 0 OR Deleted IS NULL)
            AND Number IS NOT NULL
            AND Trim(Number) <> ''
            AND (Phone IS NULL OR Trim(Phone) = '')
        """

    row = cursor.execute(
        f"""
        SELECT TOP 1
            GroupPtr,
            IdleNotLimited,
            NoFacility,
            Status,
            BgPtr,
            SendSms,
            SendMail,
            UniPassMode
        FROM Users
        WHERE {where_sql}
        ORDER BY UserPtr DESC
        """
    ).fetchone()
    if row is None:
        return {}
    return {
        "GroupPtr": row.GroupPtr,
        "IdleNotLimited": row.IdleNotLimited,
        "NoFacility": row.NoFacility,
        "Status": row.Status,
        "BgPtr": row.BgPtr,
        "SendSms": row.SendSms,
        "SendMail": row.SendMail,
        "UniPassMode": row.UniPassMode,
    }


def _build_identity(cursor: pyodbc.Cursor, key_type: str, normalized_key_value: str) -> RealGateIdentity:
    number_u = _generate_unique_number_u(cursor)
    if key_type == "Phone":
        return RealGateIdentity(number=None, phone=normalized_key_value, number_u=number_u, number_mifare=None)
    return RealGateIdentity(number=normalized_key_value, phone=None, number_u=number_u, number_mifare=None)


def _normalize_optional_phone(value: Any) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def _normalize_contact_phone(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_phone(str(value))


def _normalize_optional_text(value: Any) -> str:
    if value is None:
        return ""
    return "".join(str(value).upper().split())


def _find_existing_user_ptr(cursor: pyodbc.Cursor, key_type: str, normalized_key_value: str) -> int | None:
    rows = cursor.execute(
        """
        SELECT UserPtr, Phone, Number, Deleted
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()
    for row in rows:
        if bool(row.Deleted):
            continue
        if key_type == "Phone":
            if _normalize_optional_phone(row.Phone) == normalized_key_value:
                return int(row.UserPtr)
            continue
        if _normalize_optional_text(row.Number) == normalized_key_value:
            return int(row.UserPtr)
    return None


def _find_reusable_deleted_user_ptr(cursor: pyodbc.Cursor, key_type: str, normalized_key_value: str) -> int | None:
    rows = cursor.execute(
        """
        SELECT UserPtr, Phone, Number, Deleted
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()
    for row in rows:
        if not bool(row.Deleted):
            continue
        if key_type == "Phone":
            if _normalize_optional_phone(row.Phone) == normalized_key_value:
                return int(row.UserPtr)
            continue
        if _normalize_optional_text(row.Number) == normalized_key_value:
            return int(row.UserPtr)
    return None


def _to_access_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=None)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _insert_real_user(
    cursor: pyodbc.Cursor,
    *,
    key_type: str,
    normalized_key_value: str,
    phone_number: str | None,
    resident_name: str,
    is_visitor: bool,
    expires_at: datetime | None,
) -> int:
    key_type_value = _sample_key_type(cursor, key_type)
    defaults = _sample_user_defaults(cursor, key_type)
    last_name, first_name, father_name = _split_name(resident_name)
    identity = _build_identity(cursor, key_type, normalized_key_value)
    access_expires_at = _to_access_datetime(expires_at)

    columns: list[str] = []
    params: list[Any] = []

    def add(column: str, value: Any) -> None:
        if value is None:
            return
        columns.append(f"[{column}]")
        params.append(value)

    add("KeyType", key_type_value)
    add("Number", identity.number)
    add("NumberU", identity.number_u)
    add("NumberMifare", identity.number_mifare)
    add("Phone", _normalize_contact_phone(phone_number) or identity.phone)
    add("LastName", last_name)
    add("FirstName", first_name)
    add("FatherName", father_name)
    add("Deleted", False)
    add("UseExpiry", access_expires_at is not None)
    add("ExpiryDate", access_expires_at)
    add("ExpiryTime", access_expires_at)
    add("Visitor", is_visitor)

    for column in ("GroupPtr", "IdleNotLimited", "NoFacility", "Status", "BgPtr", "SendSms", "SendMail", "UniPassMode"):
        add(column, defaults.get(column))

    sql = f"INSERT INTO Users ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(params))})"
    cursor.execute(sql, params)
    return int(cursor.execute("SELECT @@IDENTITY").fetchval())


def _reactivate_real_user(
    cursor: pyodbc.Cursor,
    *,
    user_ptr: int,
    key_type: str,
    normalized_key_value: str,
    phone_number: str | None,
    resident_name: str,
    is_visitor: bool,
    expires_at: datetime | None,
) -> int:
    access_expires_at = _to_access_datetime(expires_at)
    last_name, first_name, father_name = _split_name(resident_name)
    assignments = [
        "[Deleted] = ?",
        "[UseExpiry] = ?",
        "[ExpiryDate] = ?",
        "[ExpiryTime] = ?",
        "[Visitor] = ?",
    ]
    params: list[Any] = [
        False,
        access_expires_at is not None,
        access_expires_at,
        access_expires_at,
        is_visitor,
    ]
    if key_type == "Phone":
        assignments.append("[Phone] = ?")
        params.append(normalized_key_value)
    else:
        assignments.append("[Number] = ?")
        params.append(normalized_key_value)
        if phone_number is not None:
            assignments.append("[Phone] = ?")
            params.append(_normalize_contact_phone(phone_number))
    if last_name is not None:
        assignments.append("[LastName] = ?")
        params.append(last_name)
    if first_name is not None:
        assignments.append("[FirstName] = ?")
        params.append(first_name)
    if father_name is not None:
        assignments.append("[FatherName] = ?")
        params.append(father_name)

    params.append(user_ptr)
    cursor.execute(f"UPDATE Users SET {', '.join(assignments)} WHERE UserPtr = ?", params)
    return user_ptr


def _reader_exists(cursor: pyodbc.Cursor, access_point_id: int) -> bool:
    cursor.execute("SELECT TOP 1 RdrPtr FROM Readers WHERE RdrPtr = ?", (access_point_id,))
    return cursor.fetchone() is not None


def _default_permission_template() -> dict[str, Any]:
    return {
        "InnerNum": False,
        "Always": True,
        "Schedule1": False,
        "Schedule2": False,
        "Schedule3": False,
        "Schedule4": False,
        "Schedule5": False,
        "Schedule6": False,
        "Schedule7": False,
        "RecordState": 0,
        "APB": False,
        "Inside": False,
        "CardType": None,
        "CardCode": None,
        "NoEntry": False,
        "NoExit": False,
    }


def _permission_template_for_reader(cursor: pyodbc.Cursor, access_point_id: int) -> dict[str, Any]:
    row = cursor.execute(
        """
        SELECT TOP 1
            InnerNum,
            Always,
            Schedule1,
            Schedule2,
            Schedule3,
            Schedule4,
            Schedule5,
            Schedule6,
            Schedule7,
            RecordState,
            APB,
            Inside,
            CardType,
            CardCode,
            NoEntry,
            NoExit
        FROM AccessTable
        WHERE RdrPtr = ?
        ORDER BY UserPtr DESC
        """,
        (access_point_id,),
    ).fetchone()
    if row is None:
        return _default_permission_template()
    return {
        "InnerNum": row.InnerNum,
        "Always": row.Always,
        "Schedule1": row.Schedule1,
        "Schedule2": row.Schedule2,
        "Schedule3": row.Schedule3,
        "Schedule4": row.Schedule4,
        "Schedule5": row.Schedule5,
        "Schedule6": row.Schedule6,
        "Schedule7": row.Schedule7,
        "RecordState": row.RecordState,
        "APB": row.APB,
        "Inside": row.Inside,
        "CardType": row.CardType,
        "CardCode": row.CardCode,
        "NoEntry": row.NoEntry,
        "NoExit": row.NoExit,
    }


def _ensure_access_permissions(cursor: pyodbc.Cursor, user_ptr: int, access_point_ids: Iterable[int]) -> None:
    for access_point_id in access_point_ids:
        if not _reader_exists(cursor, access_point_id):
            raise ValueError(f"Access point {access_point_id} was not found in Readers")
        cursor.execute(
            "SELECT TOP 1 UserPtr FROM AccessTable WHERE UserPtr = ? AND RdrPtr = ?",
            (user_ptr, access_point_id),
        )
        if cursor.fetchone() is not None:
            continue

        template = _permission_template_for_reader(cursor, access_point_id)
        cursor.execute(
            """
            INSERT INTO AccessTable
            (
                RdrPtr,
                UserPtr,
                InnerNum,
                Always,
                Schedule1,
                Schedule2,
                Schedule3,
                Schedule4,
                Schedule5,
                Schedule6,
                Schedule7,
                RecordState,
                APB,
                Inside,
                CardType,
                CardCode,
                NoEntry,
                NoExit
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                access_point_id,
                user_ptr,
                template["InnerNum"],
                template["Always"],
                template["Schedule1"],
                template["Schedule2"],
                template["Schedule3"],
                template["Schedule4"],
                template["Schedule5"],
                template["Schedule6"],
                template["Schedule7"],
                template["RecordState"],
                template["APB"],
                template["Inside"],
                template["CardType"],
                template["CardCode"],
                template["NoEntry"],
                template["NoExit"],
            ),
        )


def _upsert_real_user(
    cursor: pyodbc.Cursor,
    *,
    key_type: str,
    normalized_key_value: str,
    phone_number: str | None,
    resident_name: str,
    is_visitor: bool,
    expires_at: datetime | None,
    access_point_ids: list[int],
) -> int:
    existing_user_ptr = _find_existing_user_ptr(cursor, key_type, normalized_key_value)
    if existing_user_ptr is not None:
        access_expires_at = _to_access_datetime(expires_at)
        cursor.execute(
            """
            UPDATE Users
            SET Deleted = ?, UseExpiry = ?, ExpiryDate = ?, ExpiryTime = ?, Visitor = ?
            WHERE UserPtr = ?
            """,
            (
                False,
                access_expires_at is not None,
                access_expires_at,
                access_expires_at,
                is_visitor,
                existing_user_ptr,
            ),
        )
        if phone_number is not None and key_type != "Phone":
            cursor.execute("UPDATE Users SET Phone = ? WHERE UserPtr = ?", (_normalize_contact_phone(phone_number), existing_user_ptr))
        _ensure_access_permissions(cursor, existing_user_ptr, access_point_ids)
        return existing_user_ptr

    reusable_user_ptr = _find_reusable_deleted_user_ptr(cursor, key_type, normalized_key_value)
    if reusable_user_ptr is not None:
        user_ptr = _reactivate_real_user(
            cursor,
            user_ptr=reusable_user_ptr,
            key_type=key_type,
            normalized_key_value=normalized_key_value,
            phone_number=phone_number,
            resident_name=resident_name,
            is_visitor=is_visitor,
            expires_at=expires_at,
        )
        _ensure_access_permissions(cursor, user_ptr, access_point_ids)
        return user_ptr

    user_ptr = _insert_real_user(
        cursor,
        key_type=key_type,
        normalized_key_value=normalized_key_value,
        phone_number=phone_number,
        resident_name=resident_name,
        is_visitor=is_visitor,
        expires_at=expires_at,
    )
    _ensure_access_permissions(cursor, user_ptr, access_point_ids)
    return user_ptr


def add_permanent_key(
    key_type: str,
    key_value: str,
    phone_number: str | None,
    access_point_ids: list[int],
    resident_name: str = "Resident",
) -> int:
    validated_key_type = _validate_key_type(key_type)
    normalized_key_value = _normalize_key_value(validated_key_type, key_value)
    validated_points = _validate_access_point_ids(access_point_ids)
    with _transaction_cursor() as (_, cursor):
        return _upsert_real_user(
            cursor,
            key_type=validated_key_type,
            normalized_key_value=normalized_key_value,
            phone_number=phone_number,
            resident_name=resident_name,
            is_visitor=False,
            expires_at=None,
            access_point_ids=validated_points,
        )


def add_temporary_key(
    key_type: str,
    key_value: str,
    phone_number: str | None,
    expires_at: datetime,
    access_point_ids: list[int],
) -> int:
    validated_key_type = _validate_key_type(key_type)
    normalized_key_value = _normalize_key_value(validated_key_type, key_value)
    validated_points = _validate_access_point_ids(access_point_ids)
    if not isinstance(expires_at, datetime):
        raise ValueError("expires_at must be a datetime instance")
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("expires_at must be in the future")

    with _transaction_cursor() as (_, cursor):
        return _upsert_real_user(
            cursor,
            key_type=validated_key_type,
            normalized_key_value=normalized_key_value,
            phone_number=phone_number,
            resident_name=normalized_key_value,
            is_visitor=True,
            expires_at=expires_at,
            access_point_ids=validated_points,
        )


def remove_key(key_id: int) -> bool:
    if not isinstance(key_id, int) or key_id <= 0:
        raise ValueError("key_id must be a positive integer")

    with _transaction_cursor() as (_, cursor):
        cursor.execute("SELECT TOP 1 UserPtr FROM Users WHERE UserPtr = ?", (key_id,))
        row = cursor.fetchone()
        if row is None:
            return False

        cursor.execute("DELETE FROM AccessTable WHERE UserPtr = ?", (key_id,))
        cursor.execute(
            """
            UPDATE Users
            SET Deleted = ?, UseExpiry = ?, ExpiryDate = ?, ExpiryTime = ?
            WHERE UserPtr = ?
            """,
            (True, False, None, None, key_id),
        )
        return True


def _combine_expiry(expiry_date: Any, expiry_time: Any) -> datetime | None:
    if expiry_date is None and expiry_time is None:
        return None

    def _extract_date(value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return None

    def _extract_time(value: Any) -> time | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, time):
            return value
        return None

    date_part = _extract_date(expiry_date) or _extract_date(expiry_time)
    time_part = _extract_time(expiry_time) or _extract_time(expiry_date) or time(23, 59, 59)
    if date_part is None:
        return None
    return datetime.combine(date_part, time_part)


def cleanup_expired_keys(now: datetime | None = None) -> int:
    current_time = _to_access_datetime(now) if now is not None else datetime.now()
    removed = 0
    with _transaction_cursor() as (_, cursor):
        rows = cursor.execute(
            """
            SELECT UserPtr, UseExpiry, ExpiryDate, ExpiryTime, Deleted
            FROM Users
            WHERE (Deleted = 0 OR Deleted IS NULL)
              AND UseExpiry = True
            """
        ).fetchall()
        for row in rows:
            expiry = _combine_expiry(row.ExpiryDate, row.ExpiryTime)
            if expiry is None or expiry >= current_time:
                continue
            cursor.execute("DELETE FROM AccessTable WHERE UserPtr = ?", (int(row.UserPtr),))
            cursor.execute(
                """
                UPDATE Users
                SET Deleted = ?, UseExpiry = ?, ExpiryDate = ?, ExpiryTime = ?
                WHERE UserPtr = ?
                """,
                (True, False, None, None, int(row.UserPtr)),
            )
            removed += 1
    return removed


def get_access_points() -> list[dict[str, Any]]:
    with _readonly_cursor() as (_, cursor):
        rows = cursor.execute(
            """
            SELECT RdrPtr, Name
            FROM Readers
            WHERE Name IS NOT NULL
              AND Trim(Name) <> ''
            ORDER BY Name
            """
        ).fetchall()
        return [{"id": int(row.RdrPtr), "name": str(row.Name)} for row in rows]


def _resolve_user_ptr(cursor: pyodbc.Cursor, external_key_id: str | None) -> int | None:
    if external_key_id is None:
        return None

    value = str(external_key_id).strip()
    if not value:
        return None

    if value.isdigit():
        cursor.execute(
            """
            SELECT TOP 1 UserPtr
            FROM Users
            WHERE UserPtr = ?
              AND (Deleted = 0 OR Deleted IS NULL)
            """,
            (int(value),),
        )
        row = cursor.fetchone()
        if row is not None:
            return int(row.UserPtr)

    normalized_phone = "".join(ch for ch in value if ch.isdigit())
    normalized_text = "".join(value.upper().split())
    rows = cursor.execute(
        """
        SELECT UserPtr, Phone, Number, Deleted
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()
    for row in rows:
        if bool(row.Deleted):
            continue
        if normalized_phone and _normalize_optional_phone(row.Phone) == normalized_phone:
            return int(row.UserPtr)
        if normalized_text and _normalize_optional_text(row.Number) == normalized_text:
            return int(row.UserPtr)
    return None


def _user_is_active(cursor: pyodbc.Cursor, user_ptr: int) -> bool:
    row = cursor.execute(
        """
        SELECT TOP 1 Deleted, UseExpiry, ExpiryDate, ExpiryTime
        FROM Users
        WHERE UserPtr = ?
        """,
        (user_ptr,),
    ).fetchone()
    if row is None or bool(row.Deleted):
        return False
    if not bool(row.UseExpiry):
        return True
    expiry = _combine_expiry(row.ExpiryDate, row.ExpiryTime)
    if expiry is None:
        return True
    return expiry >= datetime.now()


def _has_user_permission(cursor: pyodbc.Cursor, user_ptr: int, access_point_id: int) -> bool:
    if not _user_is_active(cursor, user_ptr):
        return False
    cursor.execute(
        """
        SELECT TOP 1 UserPtr
        FROM AccessTable
        WHERE UserPtr = ? AND RdrPtr = ?
        """,
        (user_ptr, access_point_id),
    )
    return cursor.fetchone() is not None


def get_key_permissions(external_key_id: str) -> list[dict[str, Any]]:
    with _readonly_cursor() as (_, cursor):
        user_ptr = _resolve_user_ptr(cursor, external_key_id)
        if user_ptr is None:
            return []
        rows = cursor.execute(
            """
            SELECT a.RdrPtr, r.Name
            FROM AccessTable AS a
            LEFT JOIN Readers AS r ON r.RdrPtr = a.RdrPtr
            WHERE a.UserPtr = ?
            ORDER BY r.Name
            """,
            (user_ptr,),
        ).fetchall()
        return [{"access_point_id": int(row.RdrPtr), "access_point_name": str(row.Name or "")} for row in rows]


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


def _build_synthetic_wiegand_credential(user_ptr: int, access_point_id: int) -> dict[str, Any]:
    facility_code, card_number = _next_wiegand_values(
        key_id=user_ptr,
        user_id=user_ptr,
        access_point_id=access_point_id,
    )
    packet = GateController.build_wiegand26_packet(facility_code=facility_code, card_number=card_number)
    return {
        "access_point_id": access_point_id,
        **packet.as_dict(),
    }


def get_wiegand_credentials(external_key_id: str) -> list[dict[str, Any]]:
    with _readonly_cursor() as (_, cursor):
        user_ptr = _resolve_user_ptr(cursor, external_key_id)
        if user_ptr is None:
            return []
        rows = cursor.execute(
            """
            SELECT RdrPtr
            FROM AccessTable
            WHERE UserPtr = ?
            ORDER BY RdrPtr
            """,
            (user_ptr,),
        ).fetchall()
        return [_build_synthetic_wiegand_credential(user_ptr=user_ptr, access_point_id=int(row.RdrPtr)) for row in rows]


def _send_wiegand26(access_point_id: int, credential: dict[str, Any], external_key_id: str | None = None) -> GateOpenResponse:
    controller = GateController.from_env()
    result = controller.open_gate(
        gate_id=str(access_point_id),
        access_point_id=access_point_id,
        facility_code=int(credential["facility_code"]),
        card_number=int(credential["card_number"]),
    )
    details = {
        "external_key_id": external_key_id,
        **(result.details or {}),
    }
    return GateOpenResponse(
        success=result.success,
        message=result.message,
        error_code=result.error_code,
        details=details,
    )


def open_access_point(access_point_id: int, external_key_id: str | None = None) -> dict[str, Any]:
    if not isinstance(access_point_id, int) or access_point_id <= 0:
        raise ValueError("access_point_id must be a positive integer")

    with _readonly_cursor() as (_, cursor):
        cursor.execute("SELECT TOP 1 RdrPtr FROM Readers WHERE RdrPtr = ?", (access_point_id,))
        if cursor.fetchone() is None:
            result = GateOpenResponse(
                success=False,
                error_code="access_point_not_found",
                message="Access point not found in GATE database",
            )
            return {
                "success": result.success,
                "error_code": result.error_code,
                "message": result.message,
                "details": result.details,
            }

        user_ptr = _resolve_user_ptr(cursor, external_key_id)
        if external_key_id is not None and user_ptr is None:
            result = GateOpenResponse(
                success=False,
                error_code="key_not_found",
                message="Active key is not found in GATE database",
            )
            return {
                "success": result.success,
                "error_code": result.error_code,
                "message": result.message,
                "details": result.details,
            }
        if user_ptr is None:
            result = GateOpenResponse(
                success=False,
                error_code="key_not_found",
                message="Open by key requires external_key_id",
            )
            return {
                "success": result.success,
                "error_code": result.error_code,
                "message": result.message,
                "details": result.details,
            }
        if not _has_user_permission(cursor, user_ptr, access_point_id):
            result = GateOpenResponse(
                success=False,
                error_code="access_denied",
                message="Key has no permission for access point",
            )
            return {
                "success": result.success,
                "error_code": result.error_code,
                "message": result.message,
                "details": result.details,
            }

        credential = _build_synthetic_wiegand_credential(user_ptr=user_ptr, access_point_id=access_point_id)
        transport_result = _send_wiegand26(
            access_point_id=access_point_id,
            credential=credential,
            external_key_id=external_key_id,
        )
        return {
            "success": transport_result.success,
            "error_code": transport_result.error_code,
            "message": transport_result.message,
            "details": transport_result.details,
        }
