from __future__ import annotations

import json
import os
import shutil
import tempfile
import time as time_module
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pyodbc
from backend.app.services.gate_controller import GateController
from backend.app.utils.vehicle_number import compact_vehicle_number

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MDB_PATH = _PROJECT_ROOT / "config.mdb"
_DEFAULT_ODBC_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"
_REQUIRED_TABLES = {"Users", "Readers", "AccessTable"}
ALLOWED_KEY_TYPES = {"Phone", "VehicleNumber"}
WIEGAND_BITS = 26
_ACCESS_RECORD_STATE_PENDING_SYNC = 2
_GATETERM_UI_TRANSPORTS = {"gateterm_ui", "gate_terminal_ui", "gateterm"}
# GateTerm UI strings must stay as real Unicode text for pywinauto lookups.
_GATETERM_ACCESS_WINDOW_TITLE = "Управление точками доступа"
_GATETERM_MAIN_WINDOW_TITLE = "GATE Terminal"
_GATETERM_USERS_MENU_PATH = "Бюро пропусков->Пользователи"
_GATETERM_USERS_WINDOW_TITLE = "Список пользователей"
_GATETERM_NEW_USER_WINDOW_TITLE = "Новый пользователь"
_GATETERM_USER_SEARCH_WINDOW_TITLE = "Поиск пользователя"
_GATETERM_USER_EDIT_WINDOW_TITLE = "Изменение пользователя"
_GATETERM_USER_SEARCH_FIELD_KEY_NUMBER = "Номер ключа"
_GATETERM_USER_SEARCH_FIELD_KEY_NUMBER_INDEX = 4
# Short dummy value used to initialise GateTerm's internal list object before clicking Add.
# The actual content does not matter — it just needs to trigger the search dialog flow.
_GATETERM_SEARCH_INIT_DUMMY_VALUE = "157/42325"
_GATETERM_LOGIN_WINDOW_TITLE = "Регистрация оператора"
_GATETERM_USER_EDITOR_TAB_OFFSETS = {
    "key": 40,
    "access": 145,
    "info": 260,
    "photo": 395,
}
_PHONE_READER_HINTS = (
    "gsm",
    "gate terminal",
    "terminal",
    "phone",
    "call",
    "caller",
    "telephone",
    "звон",
    "вызов",
    "телефон",
)
ACTIVE_USER_STATUS = 0
_ANONYMOUS_GSM_EVENT_INFERENCE_WINDOW_SECONDS = 30
_ANONYMOUS_GSM_EVENT_SUCCESS_CODES = frozenset({2, 8, 56, 208})


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
    candidates = _driver_candidates(preferred)
    if candidates:
        return candidates[0]
    raise RuntimeError("No compatible MDB ODBC driver was found.")


def _driver_candidates(preferred: str | None) -> list[str]:
    candidates = [
        preferred,
        "Microsoft Access Driver (*.mdb, *.accdb)",
        "Driver do Microsoft Access (*.mdb)",
        "Microsoft Access Driver (*.mdb)",
        "Microsoft Access-Treiber (*.mdb)",
    ]
    installed = {name.lower(): name for name in pyodbc.drivers()}
    resolved: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        actual = installed.get(candidate.lower(), candidate)
        key = actual.lower()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(actual)
    return resolved


def _build_connection_string(mdb_path: Path, systemdb_path: Path, *, driver: str | None = None) -> str:
    uid, pwd = _resolve_gate_credentials()
    resolved_driver = driver or _pick_driver(_env("GATE_ODBC_DRIVER", default=_DEFAULT_ODBC_DRIVER))
    return f"DRIVER={{{resolved_driver}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"


def _connect_to_gate_mdb(mdb_path: Path, systemdb_path: Path) -> pyodbc.Connection:
    preferred_driver = _env("GATE_ODBC_DRIVER", default=_DEFAULT_ODBC_DRIVER)
    errors: list[str] = []
    for driver in _driver_candidates(preferred_driver):
        try:
            return pyodbc.connect(_build_connection_string(mdb_path, systemdb_path, driver=driver))
        except pyodbc.Error as exc:
            errors.append(f"{driver}: {exc}")
    detail = "\n".join(errors) if errors else "No compatible MDB ODBC driver was found."
    raise RuntimeError(f"Failed to connect to Gate MDB with available ODBC drivers:\n{detail}")


def get_connection() -> pyodbc.Connection:
    mdb_path, systemdb_path = _resolve_gate_paths()
    return _connect_to_gate_mdb(mdb_path, systemdb_path)


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
        conn = _connect_to_gate_mdb(temp_mdb, temp_systemdb)
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
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith(("7", "8")):
        return f"00{digits[1:]}"
    if len(digits) == 10 and digits.startswith("9"):
        return f"00{digits}"
    return digits


def _looks_like_phone_reader(name: Any) -> bool:
    value = str(name or "").strip().lower()
    return any(hint in value for hint in _PHONE_READER_HINTS)


def _sample_phone_storage_value(cursor: pyodbc.Cursor) -> str | None:
    if not hasattr(cursor, "execute"):
        return None
    try:
        try:
            rows = cursor.execute(
                """
                SELECT TOP 50
                    u.Phone,
                    u.Number,
                    u.KeyType,
                    u.Deleted,
                    r.Name
                FROM (Users AS u
                    INNER JOIN AccessTable AS a ON a.UserPtr = u.UserPtr)
                    LEFT JOIN Readers AS r ON r.RdrPtr = a.RdrPtr
                WHERE (u.Deleted = 0 OR u.Deleted IS NULL)
                  AND u.Phone IS NOT NULL
                  AND Trim(u.Phone) <> ''
                ORDER BY u.UserPtr DESC, a.RdrPtr ASC
                """
            ).fetchall()
        except Exception:
            rows = []

        phone_key_type_value: Any | None = None
        inferred_phone_key_types = {
            getattr(row, "KeyType", None)
            for row in rows
            if _looks_like_phone_reader(getattr(row, "Name", None))
            and _is_phone_identity_row(row)
            and getattr(row, "KeyType", None) is not None
        }
        if len(inferred_phone_key_types) == 1:
            phone_key_type_value = next(iter(inferred_phone_key_types))

        phone_candidates: list[tuple[str, str]] = []
        for row in rows:
            if not _looks_like_phone_reader(getattr(row, "Name", None)):
                continue
            if not _is_phone_identity_row(row, phone_key_type_value=phone_key_type_value):
                continue
            raw_value = str(row.Phone if hasattr(row, "Phone") else row[0])
            normalized = raw_value.strip()
            if normalized and _normalize_optional_phone(raw_value):
                phone_candidates.append((raw_value, normalized))

        if phone_candidates:
            mode_counts = Counter(_detect_phone_storage_mode(normalized) for _, normalized in phone_candidates)
            dominant_mode = mode_counts.most_common(1)[0][0]
            dominant_candidates = [
                raw_value for raw_value, normalized in phone_candidates if _detect_phone_storage_mode(normalized) == dominant_mode
            ]
            for raw_value in dominant_candidates:
                if raw_value != raw_value.rstrip():
                    return raw_value
            if dominant_candidates:
                return dominant_candidates[0]

        row = cursor.execute(
            """
            SELECT TOP 1 Phone
            FROM Users
            WHERE (Deleted = 0 OR Deleted IS NULL)
              AND Phone IS NOT NULL
              AND Trim(Phone) <> ''
            ORDER BY UserPtr DESC
            """
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    raw_value = str(row.Phone if hasattr(row, "Phone") else row[0])
    return raw_value if raw_value.strip() else None


def _detect_phone_storage_mode(sample_value: str | None) -> str:
    value = str(sample_value or "").strip()
    digits = "".join(ch for ch in value if ch.isdigit())
    if value.startswith("+") and len(digits) == 11 and digits.startswith("7"):
        return "plus7"
    if len(digits) == 13 and digits.startswith("007"):
        return "double_zero_11"
    if len(digits) == 12 and digits.startswith("00"):
        return "legacy_00"
    if len(digits) == 11 and digits.startswith("7"):
        return "national_11"
    if len(digits) == 11 and digits.startswith("8"):
        return "domestic_11"
    if len(digits) == 10 and digits.startswith("9"):
        return "local_10"
    return "legacy_00"


def _apply_phone_storage_whitespace(sample_value: str | None, formatted_value: str) -> str:
    raw_value = str(sample_value or "")
    if not raw_value:
        return formatted_value
    leading_len = len(raw_value) - len(raw_value.lstrip())
    trailing_len = len(raw_value) - len(raw_value.rstrip())
    leading = raw_value[:leading_len]
    trailing = raw_value[len(raw_value) - trailing_len :] if trailing_len else ""
    return f"{leading}{formatted_value}{trailing}"


def _format_phone_for_storage(cursor: pyodbc.Cursor, normalized_key_value: str) -> str:
    mode = (_env("GATE_PHONE_WRITE_FORMAT", "GATE_PHONE_STORAGE_FORMAT", default="local_10") or "local_10").strip().lower()
    sample_value: str | None = None
    if mode in {"", "sample", "match_sample"}:
        sample_value = _sample_phone_storage_value(cursor)
        mode = _detect_phone_storage_mode(sample_value)

    digits = "".join(ch for ch in normalized_key_value if ch.isdigit())
    if digits.startswith("00") and len(digits) == 12:
        local10 = digits[2:]
        national11 = f"7{local10}"
    elif len(digits) == 11 and digits[0] in {"7", "8"}:
        local10 = digits[1:]
        national11 = f"7{local10}"
    elif len(digits) == 10 and digits.startswith("9"):
        local10 = digits
        national11 = f"7{local10}"
    else:
        formatted_value = normalized_key_value
        if sample_value is not None:
            return _apply_phone_storage_whitespace(sample_value, formatted_value)
        return formatted_value

    if mode in {"legacy_00", "canonical_00", "00_local10"}:
        formatted_value = f"00{local10}"
    elif mode in {"double_zero_11", "007_national11"}:
        formatted_value = f"00{national11}"
    elif mode in {"plus7", "e164", "e164_plus7"}:
        formatted_value = f"+{national11}"
    elif mode in {"national_11", "digits_11", "7xxxxxxxxxx"}:
        formatted_value = national11
    elif mode in {"domestic_11", "8xxxxxxxxxx"}:
        formatted_value = f"8{local10}"
    elif mode in {"local_10", "digits_10"}:
        formatted_value = local10
    else:
        formatted_value = normalized_key_value

    if sample_value is not None:
        return _apply_phone_storage_whitespace(sample_value, formatted_value)
    return formatted_value


def _normalize_vehicle(value: str) -> str:
    normalized = _normalize_optional_text(value)
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


def _compose_gate_user_name(
    full_name: Any,
    last_name: Any | None = None,
    first_name: Any | None = None,
    father_name: Any | None = None,
) -> str | None:
    normalized_full_name = _normalize_gate_detail(full_name)
    if normalized_full_name is not None:
        return normalized_full_name

    parts = [
        _normalize_gate_detail(last_name),
        _normalize_gate_detail(first_name),
        _normalize_gate_detail(father_name),
    ]
    visible_parts = [part for part in parts if part]
    if not visible_parts:
        return None
    return " ".join(visible_parts)


def _gate_row_resident_name(row: Any) -> str | None:
    return _compose_gate_user_name(
        getattr(row, "DisplayName", getattr(row, "Name", None)),
        getattr(row, "LastName", None),
        getattr(row, "FirstName", None),
        getattr(row, "FatherName", None),
    )


def _generate_unique_number_u(cursor: pyodbc.Cursor) -> str:
    for _ in range(64):
        candidate = uuid.uuid4().hex[:12].upper()
        cursor.execute("SELECT TOP 1 UserPtr FROM Users WHERE NumberU = ?", (candidate,))
        if cursor.fetchone() is None:
            return candidate
    raise RuntimeError("Failed to generate a unique Users.NumberU value")


def _vehicle_number_u_mode() -> str:
    raw_mode = str(_env("GATE_VEHICLE_NUMBER_U_MODE", default="plate") or "plate").strip().lower()
    if raw_mode == "random":
        return "random"
    return "plate"


def _reader_device_key_types(
    cursor: pyodbc.Cursor,
    access_point_ids: Iterable[int] | None,
    *,
    phone_reader_only: bool = False,
) -> list[Any]:
    point_ids = [int(point_id) for point_id in (access_point_ids or [])]
    if not point_ids or not hasattr(cursor, "execute"):
        return []

    key_types: list[Any] = []
    seen: set[Any] = set()
    for point_id in point_ids:
        try:
            row = cursor.execute(
                """
                SELECT TOP 1
                    r.RdrPtr,
                    r.Name,
                    d.KeyType AS DeviceKeyType
                FROM Readers AS r
                LEFT JOIN Devices AS d ON d.DevPtr = r.DevPtr
                WHERE r.RdrPtr = ?
                """,
                (point_id,),
            ).fetchone()
        except Exception:
            continue
        if row is None:
            continue
        if phone_reader_only and not _looks_like_phone_reader(getattr(row, "Name", None)):
            continue
        key_type_value = getattr(row, "DeviceKeyType", None)
        if key_type_value is None and hasattr(row, "KeyType"):
            key_type_value = getattr(row, "KeyType", None)
        if key_type_value is None and len(row) >= 3:
            key_type_value = row[2]
        if key_type_value is None or key_type_value in seen:
            continue
        seen.add(key_type_value)
        key_types.append(key_type_value)
    return key_types


def _sample_key_type(cursor: pyodbc.Cursor, key_type: str, access_point_ids: Iterable[int] | None = None) -> Any | None:
    env_name = "GATE_REAL_KEYTYPE_PHONE" if key_type == "Phone" else "GATE_REAL_KEYTYPE_VEHICLE"
    env_value = _env(env_name)
    if env_value is not None:
        try:
            return int(env_value)
        except ValueError:
            return env_value

    if key_type == "Phone":
        phone_reader_key_types = _reader_device_key_types(cursor, access_point_ids, phone_reader_only=True)
        if len(phone_reader_key_types) == 1:
            return phone_reader_key_types[0]

    reader_key_types = _reader_device_key_types(cursor, access_point_ids)
    if len(reader_key_types) == 1:
        return reader_key_types[0]

    try:
        if key_type == "Phone":
            rows = cursor.execute(
                """
                SELECT TOP 100 UserPtr, Phone, Number, KeyType, Deleted
                FROM Users
                ORDER BY UserPtr DESC
                """
            ).fetchall()
            for row in rows:
                row_key_type = getattr(row, "KeyType", None)
                if row_key_type is None:
                    continue
                if _is_phone_identity_row(row):
                    return row_key_type
            return None
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
    except Exception:
        return None
    if row is None:
        return None
    return row.KeyType if hasattr(row, "KeyType") else row[0]


def _sample_user_defaults(
    cursor: pyodbc.Cursor,
    key_type: str,
    *,
    exclude_user_ptr: int | None = None,
) -> dict[str, Any]:
    if key_type == "Phone":
        row = _sample_phone_user_defaults(cursor, exclude_user_ptr=exclude_user_ptr)
    else:
        row = _sample_vehicle_user_defaults(cursor, exclude_user_ptr=exclude_user_ptr)

    if row is None:
        return {}
    return {
        "GroupPtr": row.GroupPtr,
        "IdleNotLimited": row.IdleNotLimited,
        "NoFacility": row.NoFacility,
        "BgPtr": row.BgPtr,
        "SendSms": row.SendSms,
        "SendMail": row.SendMail,
        "UniPassMode": row.UniPassMode,
    }


def _apply_user_defaults(
    cursor: pyodbc.Cursor,
    *,
    user_ptr: int,
    key_type: str,
    exclude_user_ptr: int | None = None,
) -> None:
    if not hasattr(cursor, "execute") or not hasattr(cursor, "fetchall"):
        return
    defaults = _sample_user_defaults(cursor, key_type, exclude_user_ptr=exclude_user_ptr)
    if not defaults:
        return

    assignments: list[str] = []
    params: list[Any] = []
    for column in ("GroupPtr", "IdleNotLimited", "NoFacility", "BgPtr", "SendSms", "SendMail", "UniPassMode"):
        if column not in defaults:
            continue
        assignments.append(f"[{column}] = ?")
        params.append(defaults[column])

    if not assignments:
        return

    params.append(int(user_ptr))
    cursor.execute(f"UPDATE Users SET {', '.join(assignments)} WHERE UserPtr = ?", params)


def _default_value_matches(current_value: Any, expected_value: Any) -> bool:
    if current_value is None or expected_value is None:
        return current_value is expected_value
    if isinstance(current_value, bool) or isinstance(expected_value, bool):
        return bool(current_value) == bool(expected_value)
    return current_value == expected_value


def _sync_user_defaults_if_needed(
    cursor: pyodbc.Cursor,
    *,
    user_ptr: int,
    key_type: str,
    row: Any | None = None,
    exclude_user_ptr: int | None = None,
) -> bool:
    if not hasattr(cursor, "execute"):
        return False
    defaults = _sample_user_defaults(cursor, key_type, exclude_user_ptr=exclude_user_ptr)
    if not defaults:
        return False

    source_row = row
    if source_row is None:
        source_row = cursor.execute(
            """
            SELECT TOP 1
                GroupPtr,
                IdleNotLimited,
                NoFacility,
                BgPtr,
                SendSms,
                SendMail,
                UniPassMode
            FROM Users
            WHERE UserPtr = ?
            """,
            (int(user_ptr),),
        ).fetchone()
    if source_row is None:
        return False

    assignments: list[str] = []
    params: list[Any] = []
    for column in ("GroupPtr", "IdleNotLimited", "NoFacility", "BgPtr", "SendSms", "SendMail", "UniPassMode"):
        if column not in defaults:
            continue
        expected_value = defaults[column]
        current_value = getattr(source_row, column, None)
        if _default_value_matches(current_value, expected_value):
            continue
        assignments.append(f"[{column}] = ?")
        params.append(expected_value)

    if not assignments:
        return False

    params.append(int(user_ptr))
    cursor.execute(f"UPDATE Users SET {', '.join(assignments)} WHERE UserPtr = ?", params)
    return True


def _build_identity(cursor: pyodbc.Cursor, key_type: str, normalized_key_value: str) -> RealGateIdentity:
    if key_type == "Phone":
        storage_phone = _format_phone_for_storage(cursor, normalized_key_value)
        return RealGateIdentity(
            number=normalized_key_value,
            phone=storage_phone,
            number_u=normalized_key_value,
            number_mifare=None,
        )
    return RealGateIdentity(
        number=normalized_key_value,
        phone=None,
        number_u=_resolve_vehicle_number_u(cursor, normalized_key_value=normalized_key_value),
        number_mifare=None,
    )


def _needs_vehicle_number_u_refresh(current_number_u: Any, normalized_key_value: str) -> bool:
    normalized_number_u = _normalize_optional_text(current_number_u)
    if _vehicle_number_u_mode() == "random":
        if not normalized_number_u:
            return True
        return normalized_number_u == normalized_key_value
    return normalized_number_u != normalized_key_value


def _resolve_vehicle_number_u(
    cursor: pyodbc.Cursor,
    *,
    normalized_key_value: str,
    user_ptr: int | None = None,
    current_number_u: Any | None = None,
) -> str:
    if _vehicle_number_u_mode() != "random":
        return normalized_key_value

    if current_number_u is None:
        if user_ptr is None or not hasattr(cursor, "execute"):
            return _generate_unique_number_u(cursor)

        row = cursor.execute(
            """
            SELECT TOP 1 NumberU
            FROM Users
            WHERE UserPtr = ?
            """,
            (int(user_ptr),),
        ).fetchone()
        current_number_u = getattr(row, "NumberU", None) if row is not None else None

    if _needs_vehicle_number_u_refresh(current_number_u, normalized_key_value):
        return _generate_unique_number_u(cursor)
    return str(current_number_u).strip()


def _normalize_optional_phone(value: Any) -> str:
    if value is None:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return ""
    return _normalize_phone(digits)


def _normalize_contact_phone(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_phone(str(value))


def _normalize_gate_detail(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _users_has_display_name_column(cursor: pyodbc.Cursor) -> bool:
    try:
        cursor.execute("SELECT TOP 1 [Name] FROM Users")
    except Exception:
        return False
    return True


def _set_gate_user_name_fields(cursor: pyodbc.Cursor, *, user_ptr: int, resident_name: str) -> None:
    display_name = _compose_gate_user_name(resident_name)
    last_name, first_name, father_name = _split_name(resident_name)
    assignments = []
    params: list[Any] = []
    if _users_has_display_name_column(cursor):
        assignments.append("[Name] = ?")
        params.append(display_name)
    assignments.extend(
        [
            "[LastName] = ?",
            "[FirstName] = ?",
            "[FatherName] = ?",
        ]
    )
    params.extend([last_name, first_name, father_name, int(user_ptr)])
    cursor.execute(f"UPDATE Users SET {', '.join(assignments)} WHERE UserPtr = ?", params)


def _update_phone_user_details(
    cursor: pyodbc.Cursor,
    *,
    user_ptr: int,
    plot_number: str | None,
    storage_phone: str | None,
) -> None:
    assignments: list[str] = []
    params: list[Any] = []

    normalized_plot = _normalize_gate_detail(plot_number)
    if normalized_plot is not None:
        assignments.append("[Details1] = ?")
        params.append(normalized_plot)

    normalized_storage_phone = _normalize_gate_detail(storage_phone)
    if normalized_storage_phone is not None:
        assignments.append("[Details2] = ?")
        params.append(normalized_storage_phone)

    if not assignments:
        return

    params.append(int(user_ptr))
    cursor.execute(f"UPDATE Users SET {', '.join(assignments)} WHERE UserPtr = ?", params)


def _normalize_optional_text(value: Any) -> str:
    return compact_vehicle_number(value)


def _looks_like_phone_identity_number(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return False
    if raw.startswith("+") and len(digits) == 11 and digits.startswith("79"):
        return True
    if len(digits) == 10 and digits.startswith("9"):
        return True
    if len(digits) == 11 and digits[0] in {"7", "8"} and digits[1] == "9":
        return True
    if len(digits) == 12 and digits.startswith("00") and digits[2] == "9":
        return True
    return len(digits) == 13 and digits.startswith("007") and digits[3] == "9"


def _phone_identity_values(row: Any, *, phone_key_type_value: Any | None = None) -> set[str]:
    values: set[str] = set()
    for field_name in ("Number", "NumberU"):
        raw_value = getattr(row, field_name, None)
        if not _looks_like_phone_identity_number(raw_value):
            continue
        normalized = _normalize_optional_phone(raw_value)
        if normalized:
            values.add(normalized)

    row_key_type = getattr(row, "KeyType", None)
    raw_phone = getattr(row, "Phone", None)
    if phone_key_type_value is not None and row_key_type == phone_key_type_value:
        normalized_phone = _normalize_optional_phone(raw_phone)
        if normalized_phone:
            values.add(normalized_phone)
    return values


def _phone_identity_matches(
    row: Any,
    normalized_key_value: str,
    *,
    phone_key_type_value: Any | None = None,
) -> bool:
    return normalized_key_value in _phone_identity_values(
        row,
        phone_key_type_value=phone_key_type_value,
    )


def _preferred_phone_identity_value(row: Any, *, phone_key_type_value: Any | None = None) -> str:
    raw_number = getattr(row, "Number", None)
    if _looks_like_phone_identity_number(raw_number):
        normalized_number = _normalize_optional_phone(raw_number)
        if normalized_number:
            return normalized_number

    raw_number_u = getattr(row, "NumberU", None)
    if _looks_like_phone_identity_number(raw_number_u):
        normalized_number_u = _normalize_optional_phone(raw_number_u)
        if normalized_number_u:
            return normalized_number_u

    row_key_type = getattr(row, "KeyType", None)
    raw_phone = getattr(row, "Phone", None)
    if phone_key_type_value is not None and row_key_type == phone_key_type_value:
        normalized_phone = _normalize_optional_phone(raw_phone)
        if normalized_phone:
            return normalized_phone
    return ""


def _is_phone_identity_row(row: Any, *, phone_key_type_value: Any | None = None) -> bool:
    if bool(getattr(row, "Deleted", False)):
        return False
    return bool(_phone_identity_values(row, phone_key_type_value=phone_key_type_value))


def _is_phone_user_match(row: Any, *, normalized_key_value: str, phone_key_type_value: Any | None) -> bool:
    return _phone_identity_matches(
        row,
        normalized_key_value,
        phone_key_type_value=phone_key_type_value,
    ) and _is_phone_identity_row(
        row,
        phone_key_type_value=phone_key_type_value,
    )


def _is_reusable_deleted_phone_user_match(
    row: Any,
    *,
    normalized_key_value: str,
    phone_key_type_value: Any | None,
) -> bool:
    if not _phone_identity_matches(
        row,
        normalized_key_value,
        phone_key_type_value=phone_key_type_value,
    ):
        return False

    row_key_type = getattr(row, "KeyType", None)
    if phone_key_type_value is not None and row_key_type == phone_key_type_value:
        return True

    return bool(_preferred_phone_identity_value(row, phone_key_type_value=phone_key_type_value))


def _is_vehicle_identity_row(row: Any, *, vehicle_key_type_value: Any | None = None) -> bool:
    if bool(getattr(row, "Deleted", False)):
        return False

    normalized_number = _normalize_optional_text(getattr(row, "Number", None))
    if not normalized_number:
        return False
    if _looks_like_phone_identity_number(getattr(row, "Number", None)):
        return False

    row_key_type = getattr(row, "KeyType", None)
    if vehicle_key_type_value is not None:
        return row_key_type == vehicle_key_type_value
    return True


def _find_existing_user_ptr(
    cursor: pyodbc.Cursor,
    key_type: str,
    normalized_key_value: str,
    *,
    key_type_value: Any | None = None,
) -> int | None:
    rows = cursor.execute(
        """
        SELECT UserPtr, Phone, Number, NumberU, KeyType, Deleted
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()
    for row in rows:
        if bool(row.Deleted):
            continue
        if int(row.UserPtr) <= 0:
            continue
        if key_type == "Phone":
            if _is_phone_user_match(row, normalized_key_value=normalized_key_value, phone_key_type_value=key_type_value):
                return int(row.UserPtr)
            continue
        if _normalize_optional_text(row.Number) == normalized_key_value:
            return int(row.UserPtr)
    return None


def _find_reusable_deleted_user_ptr(
    cursor: pyodbc.Cursor,
    key_type: str,
    normalized_key_value: str,
    *,
    key_type_value: Any | None = None,
) -> int | None:
    rows = cursor.execute(
        """
        SELECT UserPtr, Phone, Number, NumberU, KeyType, Deleted
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()
    for row in rows:
        if not bool(row.Deleted):
            continue
        if int(row.UserPtr) <= 0:
            continue
        if key_type == "Phone":
            if _is_reusable_deleted_phone_user_match(
                row,
                normalized_key_value=normalized_key_value,
                phone_key_type_value=key_type_value,
            ):
                return int(row.UserPtr)
            continue
        if _normalize_optional_text(row.Number) == normalized_key_value:
            return int(row.UserPtr)
    return None


def _cleanup_conflicting_phone_rows(
    cursor: pyodbc.Cursor,
    *,
    normalized_key_value: str,
    keep_user_ptr: int,
    phone_key_type_value: Any | None,
) -> None:
    if not hasattr(cursor, "execute") or not hasattr(cursor, "fetchall"):
        return
    rows = cursor.execute(
        """
        SELECT UserPtr, Phone, Number, NumberU, KeyType, Deleted
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()
    for row in rows:
        if bool(getattr(row, "Deleted", False)):
            continue
        row_user_ptr = int(getattr(row, "UserPtr", 0) or 0)
        if row_user_ptr <= 0 or row_user_ptr == keep_user_ptr:
            continue
        if not _phone_identity_matches(
            row,
            normalized_key_value,
            phone_key_type_value=phone_key_type_value,
        ):
            continue
        if _is_phone_identity_row(row, phone_key_type_value=phone_key_type_value):
            _purge_gate_user_identity(cursor, user_ptr=row_user_ptr)


def _purge_gate_user_identity(cursor: pyodbc.Cursor, *, user_ptr: int) -> None:
    scrub_token = uuid.uuid4().hex[:10].upper()
    cursor.execute("DELETE FROM AccessTable WHERE UserPtr = ?", (user_ptr,))
    cursor.execute(
        """
        UPDATE Users
        SET
            Deleted = ?,
            UseExpiry = ?,
            ExpiryDate = ?,
            ExpiryTime = ?,
            LockDate = ?,
            [Phone] = ?,
            [Number] = ?,
            [NumberU] = ?
        WHERE UserPtr = ?
        """,
        (
            True,
            False,
            None,
            None,
            None,
            None,
            f"PURGED-{user_ptr}-{scrub_token}",
            f"PURGED-{scrub_token}",
            user_ptr,
        ),
    )


def _purge_deleted_phone_identity_rows(
    cursor: pyodbc.Cursor,
    *,
    normalized_key_value: str,
    phone_key_type_value: Any | None,
) -> None:
    if not hasattr(cursor, "execute") or not hasattr(cursor, "fetchall"):
        return
    rows = cursor.execute(
        """
        SELECT UserPtr, Phone, Number, NumberU, KeyType, Deleted
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()
    for row in rows:
        if not bool(getattr(row, "Deleted", False)):
            continue
        row_user_ptr = int(getattr(row, "UserPtr", 0) or 0)
        if row_user_ptr <= 0:
            continue
        if not _phone_identity_matches(
            row,
            normalized_key_value,
            phone_key_type_value=phone_key_type_value,
        ):
            continue
        if _is_reusable_deleted_phone_user_match(
            row,
            normalized_key_value=normalized_key_value,
            phone_key_type_value=phone_key_type_value,
        ):
            _purge_gate_user_identity(cursor, user_ptr=row_user_ptr)


def _resolve_inserted_user_ptr(cursor: pyodbc.Cursor, *, number_u: str) -> int:
    identity_value = cursor.execute("SELECT @@IDENTITY").fetchval()
    try:
        resolved_identity = int(identity_value)
    except (TypeError, ValueError):
        resolved_identity = 0

    if resolved_identity > 0:
        return resolved_identity

    row = cursor.execute(
        """
        SELECT TOP 1 UserPtr
        FROM Users
        WHERE NumberU = ?
        ORDER BY UserPtr DESC
        """,
        (number_u,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Inserted Gate user was not found by NumberU")

    resolved_user_ptr = int(row.UserPtr)
    if resolved_user_ptr <= 0:
        raise RuntimeError(f"Inserted Gate user has invalid UserPtr: {resolved_user_ptr}")
    return resolved_user_ptr


def _to_access_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=None)
    return value.astimezone().replace(tzinfo=None)


def _normalize_expiry_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("expires_at must be a datetime instance")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _split_access_expiry(
    value: datetime | None,
    *,
    key_type: str | None = None,
) -> tuple[datetime | None, datetime | None]:
    access_value = _to_access_datetime(value)
    if access_value is None:
        return None, None
    expiry_date = datetime.combine(access_value.date(), time.min)
    if key_type == "Phone":
        expiry_time_value = time.min
    else:
        expiry_time_value = access_value.time().replace(microsecond=0)
    expiry_time = datetime.combine(date(1899, 12, 30), expiry_time_value)
    return expiry_date, expiry_time


def _access_lock_date(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None
    current_local = datetime.now().astimezone().replace(tzinfo=None)
    return datetime.combine(current_local.date(), time.min)


def _insert_real_user(
    cursor: pyodbc.Cursor,
    *,
    key_type_value: Any | None,
    key_type: str,
    normalized_key_value: str,
    phone_number: str | None,
    resident_name: str,
    plot_number: str | None,
    is_visitor: bool,
    expires_at: datetime | None,
) -> int:
    defaults = _sample_user_defaults(cursor, key_type)
    display_name = _compose_gate_user_name(resident_name)
    last_name, first_name, father_name = _split_name(resident_name)
    identity = _build_identity(cursor, key_type, normalized_key_value)
    expiry_date, expiry_time = _split_access_expiry(expires_at, key_type=key_type)

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
    if _users_has_display_name_column(cursor):
        add("Name", display_name)
    if key_type == "Phone":
        add("Phone", identity.phone)
    else:
        add("Phone", _normalize_contact_phone(phone_number) or identity.phone)
    add("LastName", last_name)
    add("FirstName", first_name)
    add("FatherName", father_name)
    add("Deleted", False)
    add("UseExpiry", expiry_date is not None)
    add("ExpiryDate", expiry_date)
    add("ExpiryTime", expiry_time)
    add("LockDate", _access_lock_date(expires_at))
    add("Visitor", is_visitor)
    add("Status", ACTIVE_USER_STATUS)

    for column in ("GroupPtr", "IdleNotLimited", "NoFacility", "BgPtr", "SendSms", "SendMail", "UniPassMode"):
        add(column, defaults.get(column))

    sql = f"INSERT INTO Users ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(params))})"
    cursor.execute(sql, params)
    user_ptr = _resolve_inserted_user_ptr(cursor, number_u=identity.number_u)
    if key_type == "Phone":
        _update_phone_user_details(
            cursor,
            user_ptr=user_ptr,
            plot_number=plot_number,
            storage_phone=identity.phone,
        )
    return user_ptr


def _reactivate_real_user(
    cursor: pyodbc.Cursor,
    *,
    user_ptr: int,
    key_type_value: Any | None,
    key_type: str,
    normalized_key_value: str,
    phone_number: str | None,
    resident_name: str,
    plot_number: str | None,
    is_visitor: bool,
    expires_at: datetime | None,
) -> int:
    expiry_date, expiry_time = _split_access_expiry(expires_at, key_type=key_type)
    lock_date = _access_lock_date(expires_at)
    vehicle_number_u: str | None = None
    if key_type != "Phone":
        vehicle_number_u = _resolve_vehicle_number_u(
            cursor,
            normalized_key_value=normalized_key_value,
            user_ptr=user_ptr,
        )
    assignments = [
        "[Deleted] = ?",
        "[UseExpiry] = ?",
        "[ExpiryDate] = ?",
        "[ExpiryTime] = ?",
        "[Visitor] = ?",
        "[Status] = ?",
        "[LockDate] = ?",
    ]
    params: list[Any] = [
        False,
        expiry_date is not None,
        expiry_date,
        expiry_time,
        is_visitor,
        ACTIVE_USER_STATUS,
        lock_date,
    ]
    storage_phone: str | None = None
    if key_type_value is not None:
        assignments.append("[KeyType] = ?")
        params.append(key_type_value)
    if key_type == "Phone":
        storage_phone = _format_phone_for_storage(cursor, normalized_key_value)
        assignments.append("[Phone] = ?")
        params.append(storage_phone)
        assignments.append("[Number] = ?")
        params.append(normalized_key_value)
        assignments.append("[NumberU] = ?")
        params.append(normalized_key_value)
    else:
        assignments.append("[Number] = ?")
        params.append(normalized_key_value)
        assignments.append("[NumberU] = ?")
        params.append(vehicle_number_u)
        if phone_number is not None:
            assignments.append("[Phone] = ?")
            params.append(_normalize_contact_phone(phone_number))

    params.append(user_ptr)
    cursor.execute(f"UPDATE Users SET {', '.join(assignments)} WHERE UserPtr = ?", params)
    _set_gate_user_name_fields(cursor, user_ptr=user_ptr, resident_name=resident_name)
    if key_type == "Phone":
        _update_phone_user_details(
            cursor,
            user_ptr=user_ptr,
            plot_number=plot_number,
            storage_phone=storage_phone,
        )
    _apply_user_defaults(cursor, user_ptr=user_ptr, key_type=key_type, exclude_user_ptr=user_ptr)
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


def _default_phone_permission_template() -> dict[str, Any]:
    template = _default_permission_template()
    template["CardType"] = 0
    template["CardCode"] = ""
    return template


def _permission_template_from_row(row: Any | None) -> dict[str, Any]:
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


def _permission_template_for_reader(
    cursor: pyodbc.Cursor,
    access_point_id: int,
    *,
    key_type: str | None = None,
) -> dict[str, Any]:
    if key_type == "Phone":
        phone_rows = cursor.execute(
            """
            SELECT TOP 100
                a.InnerNum,
                a.Always,
                a.Schedule1,
                a.Schedule2,
                a.Schedule3,
                a.Schedule4,
                a.Schedule5,
                a.Schedule6,
                a.Schedule7,
                a.RecordState,
                a.APB,
                a.Inside,
                a.CardType,
                a.CardCode,
                a.NoEntry,
                a.NoExit,
                u.Phone,
                u.Number,
                u.KeyType,
                u.Deleted
            FROM AccessTable AS a
            LEFT JOIN Users AS u ON u.UserPtr = a.UserPtr
            WHERE a.RdrPtr = ?
            ORDER BY a.UserPtr DESC
            """,
            (access_point_id,),
        ).fetchall()
        phone_key_type_value = _sample_key_type(cursor, "Phone", [access_point_id])
        matching_rows = [
            row
            for row in phone_rows
            if _is_phone_identity_row(row, phone_key_type_value=phone_key_type_value)
        ]
        preferred_row = next(
            (
                row
                for row in matching_rows
                if getattr(row, "CardType", None) is not None or str(getattr(row, "CardCode", "") or "").strip()
            ),
            None,
        )
        if preferred_row is not None:
            return _permission_template_from_row(preferred_row)
        if matching_rows:
            return _permission_template_from_row(matching_rows[0])
        return _default_phone_permission_template()

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
    return _permission_template_from_row(row)


def _existing_access_row(cursor: pyodbc.Cursor, user_ptr: int, access_point_id: int) -> Any | None:
    return cursor.execute(
        "SELECT TOP 1 UserPtr, InnerNum FROM AccessTable WHERE UserPtr = ? AND RdrPtr = ?",
        (user_ptr, access_point_id),
    ).fetchone()


def _prune_access_permissions(cursor: pyodbc.Cursor, user_ptr: int, allowed_access_point_ids: Iterable[int]) -> None:
    if not hasattr(cursor, "execute") or not hasattr(cursor, "fetchall"):
        return
    allowed = {int(point_id) for point_id in allowed_access_point_ids}
    rows = cursor.execute(
        "SELECT RdrPtr FROM AccessTable WHERE UserPtr = ?",
        (user_ptr,),
    ).fetchall()
    for row in rows:
        raw_reader_ptr = getattr(row, "RdrPtr", None)
        if raw_reader_ptr is None:
            raw_reader_ptr = row[0]
        access_point_id = int(raw_reader_ptr)
        if access_point_id in allowed:
            continue
        cursor.execute(
            "DELETE FROM AccessTable WHERE UserPtr = ? AND RdrPtr = ?",
            (user_ptr, access_point_id),
        )


def _verify_phone_user_state(
    cursor: pyodbc.Cursor,
    *,
    user_ptr: int,
    normalized_key_value: str,
    phone_key_type_value: Any | None,
    access_point_ids: Iterable[int],
) -> None:
    row = cursor.execute(
        """
        SELECT TOP 1
            UserPtr,
            KeyType,
            [Number],
            [NumberU],
            [Phone],
            Deleted,
            Status
        FROM Users
        WHERE UserPtr = ?
        """,
        (user_ptr,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Gate phone user verification failed: UserPtr={user_ptr} was not found after write")

    issues: list[str] = []
    expected_phone = _format_phone_for_storage(cursor, normalized_key_value)
    actual_number = str(getattr(row, "Number", "") or "")
    actual_number_u = str(getattr(row, "NumberU", "") or "")
    actual_phone = str(getattr(row, "Phone", "") or "")

    if bool(getattr(row, "Deleted", False)):
        issues.append("Deleted=True")
    if phone_key_type_value is not None and getattr(row, "KeyType", None) != phone_key_type_value:
        issues.append(f"KeyType={getattr(row, 'KeyType', None)!r}")
    if actual_number != normalized_key_value:
        issues.append(f"Number={actual_number!r}")
    if actual_number_u != normalized_key_value:
        issues.append(f"NumberU={actual_number_u!r}")
    if actual_phone != expected_phone:
        issues.append(f"Phone={actual_phone!r}")

    raw_status = getattr(row, "Status", None)
    try:
        status_value = None if raw_status is None else int(raw_status)
    except (TypeError, ValueError):
        status_value = raw_status
    if status_value is not None and status_value != ACTIVE_USER_STATUS:
        issues.append(f"Status={raw_status!r}")

    access_rows = cursor.execute(
        """
        SELECT RdrPtr
        FROM AccessTable
        WHERE UserPtr = ?
        ORDER BY RdrPtr
        """,
        (user_ptr,),
    ).fetchall()
    actual_access_ids: list[int] = []
    for item in access_rows:
        raw_reader_ptr = getattr(item, "RdrPtr", None)
        if raw_reader_ptr is None:
            raw_reader_ptr = item[0]
        actual_access_ids.append(int(raw_reader_ptr))
    actual_access_ids.sort()
    expected_access_ids = sorted(int(point_id) for point_id in access_point_ids)
    if actual_access_ids != expected_access_ids:
        issues.append(f"Access={actual_access_ids!r}")

    if issues:
        raise RuntimeError(
            "Gate phone user verification failed for "
            f"UserPtr={user_ptr}: expected Number/NumberU={normalized_key_value!r}, "
            f"Phone={expected_phone!r}, Access={expected_access_ids!r}; "
            f"got {', '.join(issues)}"
        )


def _inner_num_in_use(
    cursor: pyodbc.Cursor,
    access_point_id: int,
    inner_num: int,
    *,
    exclude_user_ptr: int | None = None,
) -> bool:
    sql = "SELECT TOP 1 UserPtr FROM AccessTable WHERE RdrPtr = ? AND InnerNum = ?"
    params: list[Any] = [access_point_id, inner_num]
    if exclude_user_ptr is not None:
        sql += " AND UserPtr <> ?"
        params.append(exclude_user_ptr)
    row = cursor.execute(sql, params).fetchone()
    return row is not None


def _next_inner_num(cursor: pyodbc.Cursor, access_point_id: int) -> int:
    row = cursor.execute(
        "SELECT MAX(InnerNum) AS MaxInnerNum FROM AccessTable WHERE RdrPtr = ?",
        (access_point_id,),
    ).fetchone()
    max_inner_num = getattr(row, "MaxInnerNum", None) if row is not None else None
    try:
        return max(int(max_inner_num), 0) + 1
    except (TypeError, ValueError):
        return 1


def _resolve_access_inner_num(
    cursor: pyodbc.Cursor,
    access_point_id: int,
    *,
    existing_row: Any | None,
) -> int:
    if existing_row is not None:
        existing_inner_num = getattr(existing_row, "InnerNum", None)
        try:
            resolved_inner_num = int(existing_inner_num)
        except (TypeError, ValueError):
            resolved_inner_num = 0
        if resolved_inner_num > 0 and not _inner_num_in_use(
            cursor,
            access_point_id,
            resolved_inner_num,
            exclude_user_ptr=int(existing_row.UserPtr),
        ):
            return resolved_inner_num

    return _next_inner_num(cursor, access_point_id)


def _ensure_access_permissions(
    cursor: pyodbc.Cursor,
    user_ptr: int,
    access_point_ids: Iterable[int],
    *,
    key_type: str | None = None,
) -> None:
    for access_point_id in access_point_ids:
        if not _reader_exists(cursor, access_point_id):
            raise ValueError(f"Access point {access_point_id} was not found in Readers")
        existing_row = _existing_access_row(cursor, user_ptr, access_point_id)

        template = _permission_template_for_reader(cursor, access_point_id, key_type=key_type)
        resolved_inner_num = _resolve_access_inner_num(
            cursor,
            access_point_id,
            existing_row=existing_row,
        )
        template_params = (
            resolved_inner_num,
            template["Always"],
            template["Schedule1"],
            template["Schedule2"],
            template["Schedule3"],
            template["Schedule4"],
            template["Schedule5"],
            template["Schedule6"],
            template["Schedule7"],
            _ACCESS_RECORD_STATE_PENDING_SYNC,
            template["APB"],
            template["Inside"],
            template["CardType"],
            template["CardCode"],
            template["NoEntry"],
            template["NoExit"],
        )

        if existing_row is not None:
            cursor.execute(
                """
                UPDATE AccessTable
                SET
                    InnerNum = ?,
                    Always = ?,
                    Schedule1 = ?,
                    Schedule2 = ?,
                    Schedule3 = ?,
                    Schedule4 = ?,
                    Schedule5 = ?,
                    Schedule6 = ?,
                    Schedule7 = ?,
                    RecordState = ?,
                    APB = ?,
                    Inside = ?,
                    CardType = ?,
                    CardCode = ?,
                    NoEntry = ?,
                    NoExit = ?
                WHERE UserPtr = ? AND RdrPtr = ?
                """,
                template_params + (user_ptr, access_point_id),
            )
            continue

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
            ) + template_params,
        )


def _upsert_real_user(
    cursor: pyodbc.Cursor,
    *,
    key_type: str,
    normalized_key_value: str,
    phone_number: str | None,
    resident_name: str,
    plot_number: str | None,
    is_visitor: bool,
    expires_at: datetime | None,
    access_point_ids: list[int],
) -> int:
    key_type_value = _sample_key_type(cursor, key_type, access_point_ids)
    existing_user_ptr = _find_existing_user_ptr(
        cursor,
        key_type,
        normalized_key_value,
        key_type_value=key_type_value,
    )
    if existing_user_ptr is not None:
        expiry_date, expiry_time = _split_access_expiry(expires_at, key_type=key_type)
        lock_date = _access_lock_date(expires_at)
        vehicle_number_u: str | None = None
        if key_type != "Phone":
            vehicle_number_u = _resolve_vehicle_number_u(
                cursor,
                normalized_key_value=normalized_key_value,
                user_ptr=existing_user_ptr,
            )
        cursor.execute(
            """
            UPDATE Users
            SET Deleted = ?, UseExpiry = ?, ExpiryDate = ?, ExpiryTime = ?, Visitor = ?, Status = ?, LockDate = ?
            WHERE UserPtr = ?
            """,
            (
                False,
                expiry_date is not None,
                expiry_date,
                expiry_time,
                is_visitor,
                ACTIVE_USER_STATUS,
                lock_date,
                existing_user_ptr,
            ),
        )
        if key_type_value is not None:
            cursor.execute("UPDATE Users SET KeyType = ? WHERE UserPtr = ?", (key_type_value, existing_user_ptr))
        if key_type == "Phone":
            storage_phone = _format_phone_for_storage(cursor, normalized_key_value)
            cursor.execute(
                "UPDATE Users SET Phone = ?, [Number] = ?, [NumberU] = ? WHERE UserPtr = ?",
                (storage_phone, normalized_key_value, normalized_key_value, existing_user_ptr),
            )
            _update_phone_user_details(
                cursor,
                user_ptr=existing_user_ptr,
                plot_number=plot_number,
                storage_phone=storage_phone,
            )
        else:
            cursor.execute(
                "UPDATE Users SET [Number] = ?, [NumberU] = ? WHERE UserPtr = ?",
                (normalized_key_value, vehicle_number_u, existing_user_ptr),
            )
        if phone_number is not None and key_type != "Phone":
            cursor.execute("UPDATE Users SET Phone = ? WHERE UserPtr = ?", (_normalize_contact_phone(phone_number), existing_user_ptr))
        _set_gate_user_name_fields(cursor, user_ptr=existing_user_ptr, resident_name=resident_name)
        _apply_user_defaults(
            cursor,
            user_ptr=existing_user_ptr,
            key_type=key_type,
            exclude_user_ptr=existing_user_ptr,
        )
        if key_type == "Phone":
            _cleanup_conflicting_phone_rows(
                cursor,
                normalized_key_value=normalized_key_value,
                keep_user_ptr=existing_user_ptr,
                phone_key_type_value=key_type_value,
            )
        _ensure_access_permissions(cursor, existing_user_ptr, access_point_ids, key_type=key_type)
        if key_type == "Phone":
            _prune_access_permissions(cursor, existing_user_ptr, access_point_ids)
            _verify_phone_user_state(
                cursor,
                user_ptr=existing_user_ptr,
                normalized_key_value=normalized_key_value,
                phone_key_type_value=key_type_value,
                access_point_ids=access_point_ids,
            )
        return existing_user_ptr

    reusable_user_ptr = _find_reusable_deleted_user_ptr(
        cursor,
        key_type,
        normalized_key_value,
        key_type_value=key_type_value,
    )
    if reusable_user_ptr is not None and key_type == "Phone":
        _purge_deleted_phone_identity_rows(
            cursor,
            normalized_key_value=normalized_key_value,
            phone_key_type_value=key_type_value,
        )
    elif reusable_user_ptr is not None:
        user_ptr = _reactivate_real_user(
            cursor,
            user_ptr=reusable_user_ptr,
            key_type_value=key_type_value,
            key_type=key_type,
            normalized_key_value=normalized_key_value,
            phone_number=phone_number,
            resident_name=resident_name,
            plot_number=plot_number,
            is_visitor=is_visitor,
            expires_at=expires_at,
        )
        if key_type == "Phone":
            _cleanup_conflicting_phone_rows(
                cursor,
                normalized_key_value=normalized_key_value,
                keep_user_ptr=user_ptr,
                phone_key_type_value=key_type_value,
            )
        _ensure_access_permissions(cursor, user_ptr, access_point_ids, key_type=key_type)
        if key_type == "Phone":
            _prune_access_permissions(cursor, user_ptr, access_point_ids)
            _verify_phone_user_state(
                cursor,
                user_ptr=user_ptr,
                normalized_key_value=normalized_key_value,
                phone_key_type_value=key_type_value,
                access_point_ids=access_point_ids,
            )
        return user_ptr

    user_ptr = _insert_real_user(
        cursor,
        key_type_value=key_type_value,
        key_type=key_type,
        normalized_key_value=normalized_key_value,
        phone_number=phone_number,
        resident_name=resident_name,
        plot_number=plot_number,
        is_visitor=is_visitor,
        expires_at=expires_at,
    )
    if key_type == "Phone":
        _cleanup_conflicting_phone_rows(
            cursor,
            normalized_key_value=normalized_key_value,
            keep_user_ptr=user_ptr,
            phone_key_type_value=key_type_value,
        )
    _ensure_access_permissions(cursor, user_ptr, access_point_ids, key_type=key_type)
    if key_type == "Phone":
        _prune_access_permissions(cursor, user_ptr, access_point_ids)
        _verify_phone_user_state(
            cursor,
            user_ptr=user_ptr,
            normalized_key_value=normalized_key_value,
            phone_key_type_value=key_type_value,
            access_point_ids=access_point_ids,
        )
    return user_ptr


def add_permanent_key(
    key_type: str,
    key_value: str,
    phone_number: str | None,
    access_point_ids: list[int],
    resident_name: str = "Resident",
    plot_number: str | None = None,
) -> int:
    validated_key_type = _validate_key_type(key_type)
    normalized_key_value = _normalize_key_value(validated_key_type, key_value)
    validated_points = _validate_access_point_ids(access_point_ids)

    if validated_key_type == "VehicleNumber":
        return add_vehicle_key_via_gateterm_ui(
            normalized_key_value,
            expires_at=None,
            access_point_ids=validated_points,
            resident_name=resident_name,
            plot_number=plot_number,
            phone_number=phone_number,
            is_visitor=False,
        )

    with _transaction_cursor() as (_, cursor):
        return _upsert_real_user(
            cursor,
            key_type=validated_key_type,
            normalized_key_value=normalized_key_value,
            phone_number=phone_number,
            resident_name=resident_name,
            plot_number=plot_number,
            is_visitor=False,
            expires_at=None,
            access_point_ids=validated_points,
        )


def add_phone_permanent_key_via_gateterm_ui(
    key_value: str,
    phone_number: str | None,
    access_point_ids: list[int],
    resident_name: str = "Resident",
    plot_number: str | None = None,
) -> int:
    del phone_number

    normalized_key_value = _normalize_phone(key_value)
    validated_points = _validate_access_point_ids(access_point_ids)
    attempts = max(1, _env_int("GATE_GATETERM_UI_CREATE_ATTEMPTS", 3))
    last_error: Exception | None = None

    for attempt_index in range(attempts):
        context = _load_phone_ui_provisioning_context(
            normalized_key_value=normalized_key_value,
            access_point_ids=validated_points,
        )
        app: Any | None = None
        try:
            app = _connect_or_start_gateterm_application()
            _prepare_gateterm_users_workspace(app)
            users_window = _open_gateterm_users_view(app)

            created_via_new_dialog = context["existing_user_ptr"] is None
            if created_via_new_dialog:
                editor_window = _open_gateterm_new_user_window(app, users_window)
                finalize_save = _finalize_gateterm_new_user_save
            else:
                _search_gateterm_user_by_key_number(app, users_window, normalized_key_value)
                editor_window = _open_gateterm_user_edit_window(app, users_window)
                finalize_save = _finalize_gateterm_user_edit_save

            _populate_gateterm_phone_pass_editor(
                editor_window,
                normalized_key_value=normalized_key_value,
                phone_storage_value=str(context["phone_storage_value"] or ""),
                resident_name=resident_name,
                plot_number=plot_number,
                desired_access_labels=set(context["desired_access_labels"]),
                current_access_labels=set(context.get("current_access_labels") or set()),
            )
            _click_gateterm_control(editor_window, 1, "ThunderRT6CommandButton", "Button")
            time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_DELAY_SECONDS", 0.75))
            finalize_save(app)

            user_ptr = _wait_for_phone_user_ptr(
                normalized_key_value=normalized_key_value,
                phone_key_type_value=context["phone_key_type_value"],
                timeout_seconds=_env_float("GATE_GATETERM_UI_CREATE_VERIFY_TIMEOUT_SECONDS", 12.0),
            )
            if created_via_new_dialog:
                refreshed_context = _load_phone_ui_provisioning_context(
                    normalized_key_value=normalized_key_value,
                    access_point_ids=validated_points,
                )
                desired_access_labels = set(refreshed_context["desired_access_labels"])
                current_access_labels = set(refreshed_context.get("current_access_labels") or set())
                if current_access_labels != desired_access_labels:
                    _search_gateterm_user_by_key_number(app, users_window, normalized_key_value)
                    editor_window = _open_gateterm_user_edit_window(app, users_window)
                    _populate_gateterm_phone_pass_editor(
                        editor_window,
                        normalized_key_value=normalized_key_value,
                        phone_storage_value=str(refreshed_context["phone_storage_value"] or ""),
                        resident_name=resident_name,
                        plot_number=plot_number,
                        desired_access_labels=desired_access_labels,
                        current_access_labels=current_access_labels,
                    )
                    _click_gateterm_control(editor_window, 1, "ThunderRT6CommandButton", "Button")
                    time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_DELAY_SECONDS", 0.75))
                    _finalize_gateterm_user_edit_save(app)
            _verify_phone_identity_persisted(
                user_ptr,
                normalized_key_value,
                context["phone_key_type_value"],
                validated_points,
            )
            try:
                _close_gateterm_users_window_if_open(app)
            except Exception:
                pass
            return user_ptr
        except Exception as exc:
            last_error = exc
            try:
                if app is None:
                    app = _connect_or_start_gateterm_application()
                _prepare_gateterm_users_workspace(app)
                _close_gateterm_users_window_if_open(app)
            except Exception:
                pass
            if attempt_index + 1 >= attempts:
                raise RuntimeError(f"GateTerm phone provisioning failed: {exc}") from exc
            time_module.sleep(_env_float("GATE_GATETERM_UI_RETRY_DELAY_SECONDS", 0.35))

    if last_error is not None and attempts < 1:
        raise RuntimeError(f"GateTerm phone provisioning failed: {last_error}") from last_error
    raise RuntimeError("GateTerm phone provisioning failed unexpectedly")


def add_vehicle_key_via_gateterm_ui(
    key_value: str,
    expires_at: datetime | None,
    access_point_ids: list[int],
    resident_name: str = "Resident",
    plot_number: str | None = None,
    phone_number: str | None = None,
    is_visitor: bool = True,
) -> int:
    normalized_key_value = _normalize_vehicle(key_value)
    validated_points = _validate_access_point_ids(access_point_ids)
    attempts = max(1, _env_int("GATE_GATETERM_UI_CREATE_ATTEMPTS", 3))
    last_error: Exception | None = None

    user_ptr: int | None = None
    for attempt_index in range(attempts):
        context = _load_vehicle_ui_provisioning_context(
            normalized_key_value=normalized_key_value,
            access_point_ids=validated_points,
        )
        app: Any | None = None
        try:
            app = _connect_or_start_gateterm_application()
            _prepare_gateterm_users_workspace(app)
            users_window = _open_gateterm_users_view(app)

            created_via_new_dialog = context["existing_user_ptr"] is None
            if created_via_new_dialog:
                # Search with a short dummy value to initialise GateTerm's internal list
                # object before clicking Add.  Using the real plate number here would be
                # wrong — the user doesn't exist yet and a long string is unnecessary.
                # Any non-empty value that triggers the search dialog is sufficient.
                _search_gateterm_user_by_key_number(app, users_window, _GATETERM_SEARCH_INIT_DUMMY_VALUE)
                editor_window = _open_gateterm_new_user_window(app, users_window)
                finalize_save = _finalize_gateterm_new_user_save
            else:
                _search_gateterm_user_by_key_number(app, users_window, normalized_key_value)
                editor_window = _open_gateterm_user_edit_window(app, users_window)
                finalize_save = _finalize_gateterm_vehicle_user_edit_save

            _populate_gateterm_vehicle_pass_editor(
                editor_window,
                normalized_key_value=normalized_key_value,
                resident_name=resident_name,
                plot_number=plot_number,
                phone_number=phone_number,
                desired_access_labels=set(context["desired_access_labels"]),
                current_access_labels=set(context.get("current_access_labels") or set()),
            )
            _click_gateterm_control(editor_window, 1, "ThunderRT6CommandButton", "Button")
            time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_DELAY_SECONDS", 0.75))
            finalize_save(app)

            user_ptr = _wait_for_vehicle_user_ptr(
                normalized_key_value=normalized_key_value,
                vehicle_key_type_value=context["vehicle_key_type_value"],
                timeout_seconds=_env_float("GATE_GATETERM_UI_CREATE_VERIFY_TIMEOUT_SECONDS", 12.0),
            )

            if created_via_new_dialog:
                refreshed_context = _load_vehicle_ui_provisioning_context(
                    normalized_key_value=normalized_key_value,
                    access_point_ids=validated_points,
                )
                desired_access_labels = set(refreshed_context["desired_access_labels"])
                current_access_labels = set(refreshed_context.get("current_access_labels") or set())
                if current_access_labels != desired_access_labels:
                    _search_gateterm_user_by_key_number(app, users_window, normalized_key_value)
                    editor_window = _open_gateterm_user_edit_window(app, users_window)
                    _populate_gateterm_vehicle_pass_editor(
                        editor_window,
                        normalized_key_value=normalized_key_value,
                        resident_name=resident_name,
                        plot_number=plot_number,
                        phone_number=phone_number,
                        desired_access_labels=desired_access_labels,
                        current_access_labels=current_access_labels,
                    )
                    _click_gateterm_control(editor_window, 1, "ThunderRT6CommandButton", "Button")
                    time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_DELAY_SECONDS", 0.75))
                    _finalize_gateterm_vehicle_user_edit_save(app)

            _verify_vehicle_identity_persisted(
                user_ptr,
                normalized_key_value,
                None,
            )
            try:
                _close_gateterm_users_window_if_open(app)
            except Exception:
                pass

            break  # GateTerm UI step succeeded; MDB patch is handled below
        except Exception as exc:
            last_error = exc
            try:
                if app is None:
                    app = _connect_or_start_gateterm_application()
                _prepare_gateterm_users_workspace(app)
                _close_gateterm_users_window_if_open(app)
            except Exception:
                pass
            if attempt_index + 1 >= attempts:
                raise RuntimeError(f"GateTerm vehicle provisioning failed: {exc}") from exc
            time_module.sleep(_env_float("GATE_GATETERM_UI_RETRY_DELAY_SECONDS", 0.35))

    if user_ptr is None:
        raise RuntimeError("GateTerm vehicle provisioning failed unexpectedly")

    # MDB patch: expiry, visitor flag, and status only.
    # Name, phone, and access permissions are now set via the GateTerm UI above.
    try:
        with _transaction_cursor() as (_, cursor):
            expiry_date, expiry_time = _split_access_expiry(expires_at, key_type="VehicleNumber")
            lock_date = _access_lock_date(expires_at)
            cursor.execute(
                """
                UPDATE Users
                SET UseExpiry = ?, ExpiryDate = ?, ExpiryTime = ?, LockDate = ?,
                    Visitor = ?, Status = ?
                WHERE UserPtr = ?
                """,
                (
                    expiry_date is not None,
                    expiry_date,
                    expiry_time,
                    lock_date,
                    is_visitor,
                    ACTIVE_USER_STATUS,
                    user_ptr,
                ),
            )
    except Exception as exc:
        import sys as _sys
        print(
            f"[gate_runtime] WARNING: MDB patch failed for vehicle user_ptr={user_ptr};"
            f" pass is registered but may need repair: {exc}",
            file=_sys.stderr,
            flush=True,
        )

    return user_ptr


def add_temporary_key(
    key_type: str,
    key_value: str,
    phone_number: str | None,
    expires_at: datetime,
    access_point_ids: list[int],
    resident_name: str = "Resident",
    plot_number: str | None = None,
) -> int:
    validated_key_type = _validate_key_type(key_type)
    normalized_key_value = _normalize_key_value(validated_key_type, key_value)
    validated_points = _validate_access_point_ids(access_point_ids)
    normalized_expires_at = _normalize_expiry_datetime(expires_at)
    if normalized_expires_at <= datetime.now(timezone.utc):
        raise ValueError("expires_at must be in the future")

    if validated_key_type == "VehicleNumber":
        return add_vehicle_key_via_gateterm_ui(
            normalized_key_value,
            expires_at=normalized_expires_at,
            access_point_ids=validated_points,
            resident_name=resident_name,
            plot_number=plot_number,
            phone_number=phone_number,
            is_visitor=True,
        )

    with _transaction_cursor() as (_, cursor):
        return _upsert_real_user(
            cursor,
            key_type=validated_key_type,
            normalized_key_value=normalized_key_value,
            phone_number=phone_number,
            resident_name=resident_name,
            plot_number=plot_number,
            is_visitor=False,
            expires_at=normalized_expires_at,
            access_point_ids=validated_points,
        )


def remove_key(key_id: int) -> bool:
    if not isinstance(key_id, int) or key_id <= 0:
        raise ValueError("key_id must be a positive integer")

    with _readonly_cursor() as (_, cursor):
        cursor.execute(
            """
            SELECT TOP 1 UserPtr, KeyType, Number, NumberU, Phone, Deleted
            FROM Users
            WHERE UserPtr = ?
            """,
            (key_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        if bool(getattr(row, "Deleted", False)):
            return _mark_gate_user_deleted(key_id)
        search_key = _resolve_gateterm_user_search_key(cursor, row)

    return _remove_key_via_gateterm_ui(key_id=key_id, normalized_key_value=search_key)


def resolve_key_id(external_key_id: str | None) -> int | None:
    with _readonly_cursor() as (_, cursor):
        return _resolve_user_ptr(cursor, external_key_id)


def _mark_gate_user_deleted(key_id: int) -> bool:
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


def _resolve_gateterm_user_search_key(cursor: pyodbc.Cursor, row: Any) -> str:
    phone_key_type_value = _sample_key_type(cursor, "Phone")
    vehicle_key_type_value = _sample_key_type(cursor, "VehicleNumber")
    if _is_phone_identity_row(row, phone_key_type_value=phone_key_type_value):
        return _normalize_phone(
            str(
                getattr(row, "Number", None)
                or getattr(row, "NumberU", None)
                or getattr(row, "Phone", None)
                or ""
            )
        )
    if _is_vehicle_identity_row(row, vehicle_key_type_value=vehicle_key_type_value):
        return _normalize_vehicle(str(getattr(row, "Number", None) or getattr(row, "NumberU", None) or ""))

    normalized_number = _normalize_optional_text(getattr(row, "Number", None))
    if normalized_number:
        return normalized_number
    normalized_number_u = _normalize_optional_text(getattr(row, "NumberU", None))
    if normalized_number_u:
        return normalized_number_u
    normalized_phone = _normalize_optional_phone(getattr(row, "Phone", None))
    if normalized_phone:
        return _normalize_phone(normalized_phone)
    raise RuntimeError(f"Gate key {int(getattr(row, 'UserPtr', 0) or 0)} has no searchable key number")


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
    expiry_time_date = _extract_date(expiry_time)
    raw_time_part = _extract_time(expiry_time) or _extract_time(expiry_date)
    if raw_time_part == time.min and expiry_time_date == date(1899, 12, 30) and date_part is not None:
        time_part = time(23, 59, 59)
    else:
        time_part = raw_time_part or time(23, 59, 59)
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


def repair_vehicle_number_u(*, include_deleted: bool = False) -> dict[str, Any]:
    repaired_user_ptrs: list[int] = []
    scanned = 0

    with _transaction_cursor() as (_, cursor):
        vehicle_key_type_value = _sample_key_type(cursor, "VehicleNumber")
        rows = cursor.execute(
            """
            SELECT UserPtr, KeyType, Number, NumberU, Deleted
            FROM Users
            ORDER BY UserPtr DESC
            """
        ).fetchall()
        for row in rows:
            user_ptr = int(getattr(row, "UserPtr", 0) or 0)
            if user_ptr <= 0:
                continue
            if not include_deleted and bool(getattr(row, "Deleted", False)):
                continue
            if not _is_vehicle_identity_row(row, vehicle_key_type_value=vehicle_key_type_value):
                continue

            scanned += 1
            normalized_number = _normalize_optional_text(getattr(row, "Number", None))
            normalized_number_u = _normalize_optional_text(getattr(row, "NumberU", None))
            resolved_number_u = _resolve_vehicle_number_u(
                cursor,
                normalized_key_value=normalized_number,
                current_number_u=getattr(row, "NumberU", None),
            )
            if normalized_number_u == _normalize_optional_text(resolved_number_u):
                defaults_updated = _sync_user_defaults_if_needed(
                    cursor,
                    user_ptr=user_ptr,
                    key_type="VehicleNumber",
                    row=row,
                    exclude_user_ptr=user_ptr,
                )
                if defaults_updated:
                    repaired_user_ptrs.append(user_ptr)
                continue

            cursor.execute(
                "UPDATE Users SET [NumberU] = ? WHERE UserPtr = ?",
                (resolved_number_u, user_ptr),
            )
            _sync_user_defaults_if_needed(
                cursor,
                user_ptr=user_ptr,
                key_type="VehicleNumber",
                row=row,
                exclude_user_ptr=user_ptr,
            )
            repaired_user_ptrs.append(user_ptr)

    return {
        "scanned": scanned,
        "updated": len(repaired_user_ptrs),
        "user_ptrs": repaired_user_ptrs,
    }


def repair_phone_identity_rows(*, include_deleted: bool = False) -> dict[str, Any]:
    repaired_user_ptrs: list[int] = []
    cleaned_user_ptrs: set[int] = set()
    scanned = 0

    with _transaction_cursor() as (_, cursor):
        phone_key_type_value = _sample_key_type(cursor, "Phone")
        rows = cursor.execute(
            """
            SELECT
                UserPtr,
                KeyType,
                Phone,
                Number,
                NumberU,
                Deleted,
                LastUsed,
                LastUsedRdrName,
                GroupPtr
            FROM Users
            ORDER BY UserPtr DESC
            """
        ).fetchall()

        rows_by_user_ptr: dict[int, Any] = {}
        phone_groups: dict[str, list[int]] = {}
        for row in rows:
            user_ptr = int(getattr(row, "UserPtr", 0) or 0)
            if user_ptr <= 0:
                continue
            if not include_deleted and bool(getattr(row, "Deleted", False)):
                continue

            rows_by_user_ptr[user_ptr] = row
            normalized_phone = _preferred_phone_identity_value(
                row,
                phone_key_type_value=phone_key_type_value,
            )
            if not normalized_phone:
                continue
            phone_groups.setdefault(normalized_phone, []).append(user_ptr)

        for normalized_phone, user_ptrs in phone_groups.items():
            candidate_rows = [rows_by_user_ptr[user_ptr] for user_ptr in user_ptrs if user_ptr in rows_by_user_ptr]
            if not candidate_rows:
                continue

            scanned += 1
            candidate_rows.sort(
                key=lambda item: (
                    0 if getattr(item, "KeyType", None) == phone_key_type_value else 1,
                    0 if _is_phone_identity_row(item, phone_key_type_value=phone_key_type_value) else 1,
                    -int(getattr(item, "UserPtr", 0) or 0),
                )
            )
            keep_row = candidate_rows[0]
            keep_user_ptr = int(getattr(keep_row, "UserPtr", 0) or 0)
            if keep_user_ptr <= 0:
                continue

            before_cleanup = {
                user_ptr
                for user_ptr in user_ptrs
                if user_ptr != keep_user_ptr and user_ptr in rows_by_user_ptr
            }
            _cleanup_conflicting_phone_rows(
                cursor,
                normalized_key_value=normalized_phone,
                keep_user_ptr=keep_user_ptr,
                phone_key_type_value=phone_key_type_value,
            )
            cleaned_user_ptrs.update(before_cleanup)

            expected_number = normalized_phone
            actual_number = _normalize_optional_phone(getattr(keep_row, "Number", None))
            actual_number_u = _normalize_optional_phone(getattr(keep_row, "NumberU", None))
            assignments: list[str] = []
            params: list[Any] = []
            current_key_type = getattr(keep_row, "KeyType", None)
            if phone_key_type_value is not None and current_key_type != phone_key_type_value:
                assignments.append("[KeyType] = ?")
                params.append(phone_key_type_value)
            if actual_number != expected_number:
                assignments.append("[Number] = ?")
                params.append(expected_number)
            if actual_number_u != expected_number:
                assignments.append("[NumberU] = ?")
                params.append(expected_number)

            current_phone = _normalize_optional_phone(getattr(keep_row, "Phone", None))
            if current_phone != expected_number:
                assignments.append("[Phone] = ?")
                params.append(_format_phone_for_storage(cursor, expected_number))

            defaults_updated = _sync_user_defaults_if_needed(
                cursor,
                user_ptr=keep_user_ptr,
                key_type="Phone",
                row=keep_row,
                exclude_user_ptr=keep_user_ptr,
            )

            if assignments:
                params.append(keep_user_ptr)
                cursor.execute(f"UPDATE Users SET {', '.join(assignments)} WHERE UserPtr = ?", params)
                if keep_user_ptr not in repaired_user_ptrs:
                    repaired_user_ptrs.append(keep_user_ptr)
            elif defaults_updated and keep_user_ptr not in repaired_user_ptrs:
                repaired_user_ptrs.append(keep_user_ptr)

    return {
        "scanned": scanned,
        "updated": len(repaired_user_ptrs),
        "user_ptrs": repaired_user_ptrs,
        "cleaned": len(cleaned_user_ptrs),
        "cleaned_user_ptrs": sorted(cleaned_user_ptrs),
    }


def repair_vehicle_visual_numbers(*, include_deleted: bool = False, limit: int = 50) -> dict[str, Any]:
    safe_limit = max(0, min(int(limit), 5000))
    if safe_limit == 0:
        return {"scanned": 0, "updated": 0, "failed": 0, "user_ptrs": [], "failures": []}

    candidates: list[int] = []
    with _readonly_cursor() as (_, cursor):
        vehicle_key_type_value = _sample_key_type(cursor, "VehicleNumber")
        has_display_name = _users_has_display_name_column(cursor)
        display_name_column = "[Name] AS DisplayName," if has_display_name else ""
        rows = cursor.execute(
            f"""
            SELECT UserPtr, KeyType, Number, NumberU, Deleted, {display_name_column}
                   LastName, FirstName, FatherName
            FROM Users
            ORDER BY UserPtr DESC
            """
        ).fetchall()
        for row in rows:
            user_ptr = int(getattr(row, "UserPtr", 0) or 0)
            if user_ptr <= 0:
                continue
            if not include_deleted and bool(getattr(row, "Deleted", False)):
                continue
            if not _is_vehicle_identity_row(row, vehicle_key_type_value=vehicle_key_type_value):
                continue

            normalized_number = _normalize_optional_text(getattr(row, "Number", None))
            normalized_number_u = _normalize_optional_text(getattr(row, "NumberU", None))
            resident_name = _gate_row_resident_name(row)
            legacy_number_u = bool(normalized_number) and normalized_number_u == normalized_number
            missing_display_name = (
                has_display_name
                and _normalize_gate_detail(getattr(row, "DisplayName", getattr(row, "Name", None))) is None
                and resident_name is not None
            )
            if not legacy_number_u and not missing_display_name:
                continue

            candidates.append(user_ptr)
            if len(candidates) >= safe_limit:
                break

    repaired_user_ptrs: list[int] = []
    failures: list[dict[str, Any]] = []
    for user_ptr in candidates:
        try:
            post_sync_vehicle_key(user_ptr)
            repaired_user_ptrs.append(user_ptr)
        except Exception as exc:
            failures.append({"user_ptr": user_ptr, "error": str(exc)})

    return {
        "scanned": len(candidates),
        "updated": len(repaired_user_ptrs),
        "failed": len(failures),
        "user_ptrs": repaired_user_ptrs,
        "failures": failures,
    }


def repair_user_display_names(*, include_deleted: bool = False) -> dict[str, Any]:
    repaired_user_ptrs: list[int] = []
    scanned = 0

    with _transaction_cursor() as (_, cursor):
        if not _users_has_display_name_column(cursor):
            return {
                "scanned": 0,
                "updated": 0,
                "user_ptrs": repaired_user_ptrs,
            }
        rows = cursor.execute(
            """
            SELECT UserPtr, [Name] AS DisplayName, LastName, FirstName, FatherName, Deleted
            FROM Users
            ORDER BY UserPtr DESC
            """
        ).fetchall()
        for row in rows:
            user_ptr = int(getattr(row, "UserPtr", 0) or 0)
            if user_ptr <= 0:
                continue
            if not include_deleted and bool(getattr(row, "Deleted", False)):
                continue

            scanned += 1
            if _compose_gate_user_name(getattr(row, "DisplayName", getattr(row, "Name", None))) is not None:
                continue

            rebuilt_name = _compose_gate_user_name(
                None,
                getattr(row, "LastName", None),
                getattr(row, "FirstName", None),
                getattr(row, "FatherName", None),
            )
            if rebuilt_name is None:
                continue

            cursor.execute("UPDATE Users SET [Name] = ? WHERE UserPtr = ?", (rebuilt_name, user_ptr))
            repaired_user_ptrs.append(user_ptr)

    return {
        "scanned": scanned,
        "updated": len(repaired_user_ptrs),
        "user_ptrs": repaired_user_ptrs,
    }


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
        candidate_user_ptr = int(value)
        if candidate_user_ptr <= 2_147_483_647:
            try:
                cursor.execute(
                    """
                    SELECT TOP 1 UserPtr
                    FROM Users
                    WHERE UserPtr = ?
                      AND (Deleted = 0 OR Deleted IS NULL)
                    """,
                    (candidate_user_ptr,),
                )
                row = cursor.fetchone()
            except pyodbc.Error:
                row = None
            if row is not None:
                resolved_user_ptr = int(row.UserPtr)
                if resolved_user_ptr > 0:
                    return resolved_user_ptr

    normalized_phone = ""
    if _looks_like_phone_identity_number(value):
        normalized_phone = _normalize_phone(value)
    normalized_text = _normalize_optional_text(value)
    rows = cursor.execute(
        """
        SELECT UserPtr, Phone, Number, NumberU, Deleted
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()
    for row in rows:
        if bool(row.Deleted):
            continue
        if int(row.UserPtr) <= 0:
            continue
        if normalized_phone and _is_phone_user_match(
            row,
            normalized_key_value=normalized_phone,
            phone_key_type_value=None,
        ):
            return int(row.UserPtr)
        if normalized_text and (
            _normalize_optional_text(row.Number) == normalized_text
            or _normalize_optional_text(getattr(row, "NumberU", None)) == normalized_text
        ):
            return int(row.UserPtr)
    return None


def _user_is_active(cursor: pyodbc.Cursor, user_ptr: int) -> bool:
    row = cursor.execute(
        """
        SELECT TOP 1 Deleted, UseExpiry, ExpiryDate, ExpiryTime, Status
        FROM Users
        WHERE UserPtr = ?
        """,
        (user_ptr,),
    ).fetchone()
    if row is None or bool(row.Deleted):
        return False
    raw_status = getattr(row, "Status", None)
    if raw_status is not None and int(raw_status) != ACTIVE_USER_STATUS:
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


def _load_gate_user_event_identities(user_ptrs: Iterable[int]) -> dict[int, dict[str, str | None]]:
    normalized_user_ptrs = sorted({int(user_ptr) for user_ptr in user_ptrs if int(user_ptr) > 0})
    if not normalized_user_ptrs:
        return {}

    placeholders = ", ".join("?" for _ in normalized_user_ptrs)
    with _readonly_cursor() as (_, cursor):
        display_name_column = "[Name] AS DisplayName," if _users_has_display_name_column(cursor) else ""
        rows = cursor.execute(
            f"""
            SELECT UserPtr, {display_name_column} LastName, FirstName, FatherName, [Number], NumberU, Phone
            FROM Users
            WHERE UserPtr IN ({placeholders})
            """,
            tuple(normalized_user_ptrs),
        ).fetchall()

    identities: dict[int, dict[str, str | None]] = {}
    for row in rows:
        user_ptr = int(getattr(row, "UserPtr", 0) or 0)
        if user_ptr <= 0:
            continue

        raw_number = getattr(row, "Number", None)
        raw_number_u = getattr(row, "NumberU", None)
        raw_phone = getattr(row, "Phone", None)
        normalized_number = _normalize_optional_text(raw_number)
        normalized_number_u = _normalize_optional_text(raw_number_u)
        normalized_phone = _normalize_optional_phone(raw_phone) or None
        normalized_phone_key = _preferred_phone_identity_value(row) or None

        key_type: str | None = None
        key_value: str | None = None
        if normalized_phone_key:
            key_type = "Phone"
            key_value = normalized_phone_key
        elif normalized_number:
            key_type = "VehicleNumber"
            key_value = normalized_number
        elif normalized_number_u and _vehicle_number_u_mode() != "random":
            key_type = "VehicleNumber"
            key_value = normalized_number_u
        elif normalized_phone:
            key_type = "Phone"
            key_value = normalized_phone

        identities[user_ptr] = {
            "full_name": _compose_gate_user_name(
                getattr(row, "DisplayName", getattr(row, "Name", None)),
                getattr(row, "LastName", None),
                getattr(row, "FirstName", None),
                getattr(row, "FatherName", None),
            ),
            "key_type": key_type,
            "key_value": key_value,
        }

    return identities


def _normalize_gate_reader_label(value: Any) -> str | None:
    normalized_value = _normalize_gate_detail(value)
    if normalized_value is None:
        return None
    return " ".join(normalized_value.casefold().split())


def _phone_reader_names_by_id(cursor: pyodbc.Cursor) -> dict[int, str]:
    rows = cursor.execute(
        """
        SELECT RdrPtr, Name
        FROM Readers
        """
    ).fetchall()

    reader_names: dict[int, str] = {}
    for row in rows:
        try:
            access_point_id = int(getattr(row, "RdrPtr", 0) or 0)
        except (TypeError, ValueError):
            continue
        if access_point_id <= 0:
            continue
        reader_name = str(getattr(row, "Name", "") or "")
        if _looks_like_phone_reader(reader_name):
            reader_names[access_point_id] = reader_name
    return reader_names


def _event_int_value(event: dict[str, Any], key: str) -> int | None:
    value = event.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_supports_phone_identity_inference(
    event: dict[str, Any],
    *,
    phone_reader_access_point_ids: set[int],
) -> bool:
    user_ptr = _event_int_value(event, "user_ptr")
    if user_ptr is not None and user_ptr > 0:
        return False
    if _normalize_gate_detail(event.get("name")) is not None:
        return False
    if _normalize_gate_detail(event.get("full_name")) is not None:
        return False
    if _normalize_gate_detail(event.get("key_value")) is not None:
        return False

    event_code = _event_int_value(event, "event_code")
    if event_code not in _ANONYMOUS_GSM_EVENT_SUCCESS_CODES:
        return False

    access_point_id = _event_int_value(event, "access_point_id")
    if access_point_id is not None and access_point_id in phone_reader_access_point_ids:
        return True
    if _looks_like_phone_reader(event.get("unit")):
        return True
    return _looks_like_phone_reader(event.get("message"))


def _load_recent_phone_last_used_candidates(
    cursor: pyodbc.Cursor,
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    phone_key_type_value = _sample_key_type(cursor, "Phone")
    display_name_column = "[Name] AS DisplayName," if _users_has_display_name_column(cursor) else ""
    rows = cursor.execute(
        f"""
        SELECT TOP 500
            UserPtr,
            {display_name_column}
            LastName,
            FirstName,
            FatherName,
            [Number],
            NumberU,
            Phone,
            KeyType,
            Deleted,
            Status,
            LastUsed,
            LastUsedRdrName
        FROM Users
        WHERE LastUsed IS NOT NULL
        ORDER BY LastUsed DESC, UserPtr DESC
        """
    ).fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        user_ptr = int(getattr(row, "UserPtr", 0) or 0)
        if user_ptr <= 0:
            continue
        if not _is_phone_identity_row(row, phone_key_type_value=phone_key_type_value):
            continue
        if not _is_active_user_status(getattr(row, "Status", None)):
            continue

        last_used = getattr(row, "LastUsed", None)
        if not isinstance(last_used, datetime):
            continue
        if last_used < window_start or last_used > window_end:
            continue

        last_used_reader_ptr = getattr(row, "LastUsedRdrPtr", None)
        try:
            normalized_last_used_reader_ptr = int(last_used_reader_ptr or 0)
        except (TypeError, ValueError):
            normalized_last_used_reader_ptr = 0
        last_used_event = _normalize_gate_detail(getattr(row, "LastUsedEvent", None))
        last_used_reader_label = _normalize_gate_reader_label(getattr(row, "LastUsedRdrName", None))
        if normalized_last_used_reader_ptr <= 0 and last_used_event is None and last_used_reader_label is None:
            continue

        key_value = _preferred_phone_identity_value(row, phone_key_type_value=phone_key_type_value) or None
        if key_value is None:
            continue

        candidates.append(
            {
                "user_ptr": user_ptr,
                "full_name": _compose_gate_user_name(
                    getattr(row, "DisplayName", getattr(row, "Name", None)),
                    getattr(row, "LastName", None),
                    getattr(row, "FirstName", None),
                    getattr(row, "FatherName", None),
                ),
                "key_type": "Phone",
                "key_value": key_value,
                "last_used": last_used,
                "last_used_reader_label": last_used_reader_label,
            }
        )

    return candidates


def _match_inferred_phone_identity_for_event(
    event: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    phone_reader_names_by_id: dict[int, str],
) -> dict[str, Any] | None:
    raw_event_time = event.get("time")
    if isinstance(raw_event_time, datetime):
        event_time = raw_event_time
    else:
        try:
            event_time = datetime.fromisoformat(str(raw_event_time))
        except ValueError:
            return None

    access_point_id = _event_int_value(event, "access_point_id")
    event_reader_labels: set[str] = set()
    if access_point_id is not None:
        reader_name = phone_reader_names_by_id.get(access_point_id)
        normalized_reader_name = _normalize_gate_reader_label(reader_name)
        if normalized_reader_name is not None:
            event_reader_labels.add(normalized_reader_name)
    normalized_unit = _normalize_gate_reader_label(event.get("unit"))
    if normalized_unit is not None:
        event_reader_labels.add(normalized_unit)

    grouped_matches: dict[tuple[str | None, str | None, str | None], dict[str, Any]] = {}
    for candidate in candidates:
        last_used = candidate.get("last_used")
        if not isinstance(last_used, datetime):
            continue
        distance_seconds = abs((event_time - last_used).total_seconds())
        if distance_seconds > _ANONYMOUS_GSM_EVENT_INFERENCE_WINDOW_SECONDS:
            continue

        candidate_reader_label = candidate.get("last_used_reader_label")
        if candidate_reader_label is not None and event_reader_labels and candidate_reader_label not in event_reader_labels:
            continue

        reader_match = bool(candidate_reader_label is not None and candidate_reader_label in event_reader_labels)
        identity_key = (
            candidate.get("full_name"),
            candidate.get("key_type"),
            candidate.get("key_value"),
        )
        ranked_candidate = {
            **candidate,
            "distance_seconds": distance_seconds,
            "reader_match": reader_match,
        }
        current_best = grouped_matches.get(identity_key)
        current_rank = (
            0 if reader_match else 1,
            distance_seconds,
        )
        if current_best is None:
            grouped_matches[identity_key] = ranked_candidate
            continue
        best_rank = (
            0 if bool(current_best.get("reader_match")) else 1,
            float(current_best.get("distance_seconds", 0.0) or 0.0),
        )
        if current_rank < best_rank:
            grouped_matches[identity_key] = ranked_candidate

    if not grouped_matches:
        return None

    ranked_matches = sorted(
        grouped_matches.values(),
        key=lambda item: (
            0 if bool(item.get("reader_match")) else 1,
            float(item.get("distance_seconds", 0.0) or 0.0),
        ),
    )
    if len(ranked_matches) == 1:
        return ranked_matches[0]

    best_match = ranked_matches[0]
    second_match = ranked_matches[1]
    if bool(best_match.get("reader_match")) and not bool(second_match.get("reader_match")):
        return best_match
    return None


def _infer_anonymous_gate_event_identities(events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    candidate_events = [
        event
        for event in events
        if (_event_int_value(event, "user_ptr") or 0) <= 0
        and _normalize_gate_detail(event.get("name")) is None
        and _normalize_gate_detail(event.get("full_name")) is None
        and _normalize_gate_detail(event.get("key_value")) is None
        and _event_int_value(event, "event_code") in _ANONYMOUS_GSM_EVENT_SUCCESS_CODES
    ]
    if not candidate_events:
        return {}

    valid_event_times: list[datetime] = []
    for event in candidate_events:
        raw_event_time = event.get("time")
        if isinstance(raw_event_time, datetime):
            valid_event_times.append(raw_event_time)
            continue
        try:
            valid_event_times.append(datetime.fromisoformat(str(raw_event_time)))
        except ValueError:
            continue
    if not valid_event_times:
        return {}

    window = timedelta(seconds=_ANONYMOUS_GSM_EVENT_INFERENCE_WINDOW_SECONDS)
    window_start = min(valid_event_times) - window
    window_end = max(valid_event_times) + window

    with _readonly_cursor() as (_, cursor):
        phone_reader_names = _phone_reader_names_by_id(cursor)
        phone_reader_access_point_ids = set(phone_reader_names)
        filtered_events = [
            event
            for event in candidate_events
            if _event_supports_phone_identity_inference(
                event,
                phone_reader_access_point_ids=phone_reader_access_point_ids,
            )
        ]
        if not filtered_events:
            return {}

        candidates = _load_recent_phone_last_used_candidates(
            cursor,
            window_start=window_start,
            window_end=window_end,
        )

    inferred_by_index: dict[int, dict[str, Any]] = {}
    for event in filtered_events:
        index = _event_int_value(event, "index")
        if index is None:
            continue
        matched_identity = _match_inferred_phone_identity_for_event(
            event,
            candidates=candidates,
            phone_reader_names_by_id=phone_reader_names,
        )
        if matched_identity is None:
            continue
        inferred_by_index[index] = {
            "full_name": matched_identity.get("full_name"),
            "key_type": matched_identity.get("key_type"),
            "key_value": matched_identity.get("key_value"),
            "user_ptr": matched_identity.get("user_ptr"),
            "source": "last_used",
        }

    return inferred_by_index


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


def post_sync_phone_key(key_id: int) -> dict[str, Any]:
    if not isinstance(key_id, int) or key_id <= 0:
        raise ValueError("key_id must be a positive integer")

    with _readonly_cursor() as (_, cursor):
        row = cursor.execute(
            """
            SELECT TOP 1 UserPtr, KeyType, Number, NumberU, Phone, Deleted
            FROM Users
            WHERE UserPtr = ?
            """,
            (key_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Gate phone key {key_id} was not found after MDB write")

        phone_key_type_value = _sample_key_type(cursor, "Phone")
        if not _is_phone_identity_row(row, phone_key_type_value=phone_key_type_value):
            raise RuntimeError(f"Gate key {key_id} is not a live phone pass")

        normalized_key_value = _normalize_phone(
            str(
                getattr(row, "Number", None)
                or getattr(row, "NumberU", None)
                or getattr(row, "Phone", None)
                or ""
            )
        )
        access_rows = cursor.execute(
            """
            SELECT RdrPtr
            FROM AccessTable
            WHERE UserPtr = ?
            ORDER BY RdrPtr
            """,
            (key_id,),
        ).fetchall()
        access_point_ids: list[int] = []
        for item in access_rows:
            raw_reader_ptr = getattr(item, "RdrPtr", None)
            if raw_reader_ptr is None:
                raw_reader_ptr = item[0]
            access_point_ids.append(int(raw_reader_ptr))

    return _post_sync_phone_key_via_gateterm_ui(
        user_ptr=key_id,
        normalized_key_value=normalized_key_value,
        phone_key_type_value=phone_key_type_value,
        access_point_ids=access_point_ids,
    )


def post_sync_vehicle_key(key_id: int) -> dict[str, Any]:
    if not isinstance(key_id, int) or key_id <= 0:
        raise ValueError("key_id must be a positive integer")

    with _readonly_cursor() as (_, cursor):
        display_name_column = "[Name] AS DisplayName," if _users_has_display_name_column(cursor) else ""
        row = cursor.execute(
            f"""
            SELECT TOP 1 UserPtr, KeyType, Number, NumberU, Deleted, {display_name_column}
                   LastName, FirstName, FatherName
            FROM Users
            WHERE UserPtr = ?
            """,
            (key_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Gate vehicle key {key_id} was not found after MDB write")

        vehicle_key_type_value = _sample_key_type(cursor, "VehicleNumber")
        if not _is_vehicle_identity_row(row, vehicle_key_type_value=vehicle_key_type_value):
            raise RuntimeError(f"Gate key {key_id} is not a live vehicle pass")

        normalized_key_value = _normalize_vehicle(
            str(getattr(row, "Number", None) or getattr(row, "NumberU", None) or "")
        )
        # GateTerm materializes the visual vehicle key number only after the
        # edit dialog is opened and saved. During that save it may rewrite
        # Users.NumberU from the plate text to an internal hex identifier even
        # when the row was originally inserted in plate mode, so post-sync must
        # always allow GateTerm to choose the final internal NumberU value.
        expected_number_u = None
        resident_name = _gate_row_resident_name(row)

    return _post_sync_vehicle_key_via_gateterm_ui(
        user_ptr=key_id,
        normalized_key_value=normalized_key_value,
        expected_number_u=expected_number_u,
        resident_name=resident_name,
    )


def _remove_key_via_gateterm_ui(*, key_id: int, normalized_key_value: str) -> bool:
    attempts = max(1, _env_int("GATE_GATETERM_UI_DELETE_ATTEMPTS", 3))
    last_error: Exception | None = None

    for attempt_index in range(attempts):
        app: Any | None = None
        try:
            app = _connect_or_start_gateterm_application()
            _prepare_gateterm_users_workspace(app)
            users_window = _open_gateterm_users_view(app)
            _search_gateterm_user_by_key_number(app, users_window, normalized_key_value)
            _verify_gateterm_selected_user_key_number(app, users_window, normalized_key_value)
            _search_gateterm_user_by_key_number(app, users_window, normalized_key_value)
            users_window.set_focus()
            try:
                users_window.menu().items()[0].sub_menu().items()[2].click()
            except Exception:
                users_window.type_keys("^d")
            # GateTerm opens delete confirmation asynchronously; wait for it before leaving the user card flow.
            dialog = _wait_for_gateterm_confirmation_dialog(
                app,
                timeout_seconds=_env_float("GATE_GATETERM_UI_DELETE_CONFIRM_TIMEOUT_SECONDS", 5.0),
            )
            _confirm_gateterm_dialog(dialog)
            _confirm_gateterm_message_boxes_if_open(app)
            _wait_for_gate_user_deleted(
                key_id,
                timeout_seconds=_env_float("GATE_GATETERM_UI_DELETE_APPLY_TIMEOUT_SECONDS", 6.0),
            )

            _close_gateterm_user_edit_window_if_open(app)
            try:
                _close_gateterm_users_window_if_open(app)
            except Exception:
                pass
            return True
        except Exception as exc:
            last_error = exc
            try:
                if app is None:
                    app = _connect_or_start_gateterm_application()
                _prepare_gateterm_users_workspace(app)
                _close_gateterm_users_window_if_open(app)
            except Exception:
                pass
            if attempt_index + 1 >= attempts:
                raise RuntimeError(f"GateTerm key deletion failed: {exc}") from exc
            time_module.sleep(_env_float("GATE_GATETERM_UI_RETRY_DELAY_SECONDS", 0.35))

    if last_error is not None and attempts < 1:
        raise RuntimeError(f"GateTerm key deletion failed: {last_error}") from last_error
    raise RuntimeError("GateTerm key deletion failed unexpectedly")


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


def _configured_open_transport() -> str:
    return (_env("GATE_WIEGAND_TRANSPORT", default="dry_run") or "dry_run").strip().lower()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _find_gateterm_window(app: Any, title_fragment: str) -> Any | None:
    normalized_fragment = str(title_fragment or "").strip().casefold()
    if not normalized_fragment:
        return None

    for window in app.windows():
        try:
            window_title = str(window.window_text() or "").strip()
            if normalized_fragment in window_title.casefold():
                return app.window(handle=window.handle)
        except Exception:
            continue
    return None


def _list_gateterm_windows(app: Any) -> list[str]:
    labels: list[str] = []
    for window in app.windows():
        try:
            title = str(window.window_text() or "").strip()
            class_name = str(window.class_name() or "").strip()
            if not title and not class_name:
                continue
            labels.append(f"{title or '<untitled>'} [{class_name or '?'}]")
        except Exception:
            continue
    return labels


def _try_wait_for_gateterm_window(app: Any, title_fragment: str, *, timeout_seconds: float | None = None) -> Any | None:
    timeout = _env_float("GATE_GATETERM_UI_WINDOW_WAIT_TIMEOUT_SECONDS", 3.0)
    if timeout_seconds is not None:
        timeout = timeout_seconds
    deadline = time_module.monotonic() + max(timeout, 0.0)

    while True:
        window = _find_gateterm_window(app, title_fragment)
        if window is not None:
            return window
        if time_module.monotonic() >= deadline:
            return None
        time_module.sleep(0.1)


def _wait_for_gateterm_window_to_close(app: Any, title_fragment: str, *, timeout_seconds: float | None = None) -> None:
    timeout = _env_float("GATE_GATETERM_UI_WINDOW_WAIT_TIMEOUT_SECONDS", 3.0)
    if timeout_seconds is not None:
        timeout = timeout_seconds
    deadline = time_module.monotonic() + max(timeout, 0.0)

    while True:
        if _find_gateterm_window(app, title_fragment) is None:
            return
        if time_module.monotonic() >= deadline:
            raise RuntimeError(
                f"GateTerm window {title_fragment!r} did not close; open windows: {_list_gateterm_windows(app)!r}"
            )
        time_module.sleep(0.1)


def _wait_for_enabled_gateterm_window(app: Any, title_fragment: str, *, timeout_seconds: float | None = None) -> Any:
    timeout = _env_float("GATE_GATETERM_UI_WINDOW_WAIT_TIMEOUT_SECONDS", 3.0)
    if timeout_seconds is not None:
        timeout = timeout_seconds
    deadline = time_module.monotonic() + max(timeout, 0.0)

    while True:
        window = _find_gateterm_window(app, title_fragment)
        if window is not None:
            try:
                if window.is_enabled():
                    try:
                        window.set_focus()
                    except Exception:
                        pass
                    return window
            except Exception:
                pass
        if time_module.monotonic() >= deadline:
            raise RuntimeError(
                f"GateTerm window {title_fragment!r} is not ready; open windows: {_list_gateterm_windows(app)!r}"
            )
        time_module.sleep(0.1)


def _gateterm_window_has_menu(window: Any) -> bool:
    try:
        menu = window.menu()
        if menu is None:
            return False
        return bool(menu.items())
    except Exception:
        return False


def _find_gateterm_main_window(app: Any) -> Any | None:
    for window in app.windows():
        try:
            candidate = app.window(handle=window.handle)
            title = str(candidate.window_text() or "").strip().casefold()
            class_name = str(candidate.class_name() or "").strip()
            if "gate terminal" in title and class_name == "ThunderRT6FormDC" and _gateterm_window_has_menu(candidate):
                return candidate
        except Exception:
            continue

    main_window = _find_gateterm_window(app, _GATETERM_MAIN_WINDOW_TITLE)
    if main_window is not None and _gateterm_window_has_menu(main_window):
        return main_window

    for window in app.windows():
        try:
            candidate = app.window(handle=window.handle)
            if _gateterm_window_has_menu(candidate):
                return candidate
        except Exception:
            continue

    for window in app.windows():
        try:
            if str(window.class_name() or "") == "ThunderRT6Main":
                return app.window(handle=window.handle)
        except Exception:
            continue
    return None


def _find_gateterm_users_window(app: Any) -> Any | None:
    return _find_gateterm_window(app, _GATETERM_USERS_WINDOW_TITLE)


def _connect_or_start_gateterm_application() -> Any:
    try:
        from pywinauto import Application
    except ImportError as exc:
        raise RuntimeError(f"pywinauto is required for GateTerm UI automation: {exc}") from exc

    gate_term_exe = _env("GATE_GATETERM_EXE", default=r"C:\GATE\Terminal\GateTerm.exe")
    if not gate_term_exe:
        raise RuntimeError("GATE_GATETERM_EXE is not configured")

    last_error: Exception | None = None
    for mode in ("connect", "start"):
        try:
            app_factory = Application(backend="win32")
            if mode == "connect":
                app = app_factory.connect(path=gate_term_exe)
            else:
                app = app_factory.start(f'"{gate_term_exe}"')
                time_module.sleep(_env_float("GATE_GATETERM_UI_START_DELAY_SECONDS", 1.5))
            _complete_gateterm_operator_login_if_needed(app)
            if _find_gateterm_main_window(app) is not None:
                return app
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Failed to connect to GateTerm UI: {last_error}") from last_error


def _complete_gateterm_operator_login_if_needed(app: Any) -> None:
    login_window = _try_wait_for_gateterm_window(
        app,
        _GATETERM_LOGIN_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_LOGIN_WAIT_SECONDS", 1.0),
    )
    if login_window is None:
        return

    operator_login = str(_env("GATE_GATETERM_OPERATOR_LOGIN", default="admin") or "admin")
    operator_password = _env("GATE_GATETERM_OPERATOR_PASSWORD", default="", allow_empty=True) or ""
    _set_gateterm_text_input(
        _visible_gateterm_control_by_id(login_window, 4, "ThunderRT6TextBox", "Edit"),
        operator_login,
        field_name="GateTerm operator login",
    )
    _set_gateterm_text_input(
        _visible_gateterm_control_by_id(login_window, 5, "ThunderRT6TextBox", "Edit"),
        operator_password,
        field_name="GateTerm operator password",
    )
    _click_gateterm_control(login_window, 2, "ThunderRT6CommandButton", "Button")
    _confirm_gateterm_message_boxes_if_open(app)
    _wait_for_gateterm_window_to_close(
        app,
        _GATETERM_LOGIN_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_LOGIN_CLOSE_DELAY_SECONDS", 3.0),
    )
    _wait_for_enabled_gateterm_window(
        app,
        _GATETERM_MAIN_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_MAIN_OPEN_DELAY_SECONDS", 3.0),
    )


def _visible_gateterm_control_by_id(window: Any, control_id: int, *class_names: str) -> Any:
    for class_name in class_names or ("",):
        lookup: dict[str, Any] = {"control_id": control_id}
        if class_name:
            lookup["class_name"] = class_name
        try:
            control = window.child_window(**lookup).wrapper_object()
            if control.is_visible():
                return control
        except Exception:
            continue

    for control in window.descendants():
        try:
            if int(control.control_id()) != int(control_id):
                continue
            wrapper = control.wrapper_object()
            if not wrapper.is_visible():
                continue
            if class_names and wrapper.class_name() not in class_names:
                continue
            return wrapper
        except Exception:
            continue

    raise RuntimeError(
        f"GateTerm UI control with control_id={control_id} was not found in {window.window_text()!r}"
    )


def _click_gateterm_control(window: Any, control_id: int, *class_names: str) -> None:
    control = _visible_gateterm_control_by_id(window, control_id, *class_names)
    try:
        control.click()
    except Exception:
        control.click_input()


def _is_invalid_window_handle_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    exc_type = type(exc).__name__.lower()
    return (
        "invalidwindowhandle" in exc_type
        or "invalid window handle" in message
        or "not a vaild window handle" in message
        or "winerror 1400" in message
        or "недопустимый дескриптор окна" in message
    )


def _window_still_open(app: Any, title_fragment: str) -> bool:
    return _find_gateterm_window(app, title_fragment) is not None


def _dismiss_gateterm_window_via_escape(app: Any, title_fragment: str) -> None:
    window = _find_gateterm_window(app, title_fragment)
    if window is None:
        return
    try:
        window.type_keys("{ESC}")
    except Exception as exc:
        if _is_invalid_window_handle_error(exc) and not _window_still_open(app, title_fragment):
            return
        try:
            window.close()
            return
        except Exception:
            raise exc


def _close_gateterm_search_window_if_open(app: Any) -> None:
    search_window = _find_gateterm_window(app, _GATETERM_USER_SEARCH_WINDOW_TITLE)
    if search_window is None:
        return
    try:
        _click_gateterm_control(search_window, 5, "ThunderRT6CommandButton", "Button")
    except Exception:
        if _window_still_open(app, _GATETERM_USER_SEARCH_WINDOW_TITLE):
            _dismiss_gateterm_window_via_escape(app, _GATETERM_USER_SEARCH_WINDOW_TITLE)
    if not _window_still_open(app, _GATETERM_USER_SEARCH_WINDOW_TITLE):
        return
    _wait_for_gateterm_window_to_close(
        app,
        _GATETERM_USER_SEARCH_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_USER_SEARCH_CLOSE_DELAY_SECONDS", 0.8),
    )


def _close_gateterm_user_edit_window_if_open(app: Any) -> None:
    edit_window = _find_gateterm_window(app, _GATETERM_USER_EDIT_WINDOW_TITLE)
    if edit_window is None:
        return
    try:
        _click_gateterm_control(edit_window, 2, "ThunderRT6CommandButton", "Button")
    except Exception:
        if _window_still_open(app, _GATETERM_USER_EDIT_WINDOW_TITLE):
            _dismiss_gateterm_window_via_escape(app, _GATETERM_USER_EDIT_WINDOW_TITLE)
    _close_gateterm_message_boxes_if_open(app)
    if not _window_still_open(app, _GATETERM_USER_EDIT_WINDOW_TITLE):
        return
    _wait_for_gateterm_window_to_close(
        app,
        _GATETERM_USER_EDIT_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_USER_EDIT_CLOSE_DELAY_SECONDS", 1.2),
    )


def _close_gateterm_new_user_window_if_open(app: Any) -> None:
    new_user_window = _find_gateterm_window(app, _GATETERM_NEW_USER_WINDOW_TITLE)
    if new_user_window is None:
        return
    # Click the Cancel button (id=2) so GateTerm's own form-close code runs cleanly.
    # Sending WM_CLOSE / Alt+F4 bypasses the VB6 Unload handler and triggers Error 91.
    try:
        _click_gateterm_control(new_user_window, 2, "ThunderRT6CommandButton", "Button")
    except Exception:
        if _window_still_open(app, _GATETERM_NEW_USER_WINDOW_TITLE):
            _dismiss_gateterm_window_via_escape(app, _GATETERM_NEW_USER_WINDOW_TITLE)
    _close_gateterm_message_boxes_if_open(app)
    if not _window_still_open(app, _GATETERM_NEW_USER_WINDOW_TITLE):
        return
    _wait_for_gateterm_window_to_close(
        app,
        _GATETERM_NEW_USER_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_NEW_USER_CLOSE_DELAY_SECONDS", 1.2),
    )


def _close_gateterm_window_if_open(app: Any, title_fragment: str, *, timeout_seconds: float) -> None:
    window = _find_gateterm_window(app, title_fragment)
    if window is None:
        return
    try:
        window.set_focus()
    except Exception:
        pass
    try:
        window.close()
    except Exception:
        try:
            window.type_keys("%{F4}")
        except Exception:
            if _window_still_open(app, title_fragment):
                _dismiss_gateterm_window_via_escape(app, title_fragment)
    if not _window_still_open(app, title_fragment):
        return
    _wait_for_gateterm_window_to_close(
        app,
        title_fragment,
        timeout_seconds=timeout_seconds,
    )


def _close_gateterm_users_window_if_open(app: Any) -> None:
    _close_gateterm_window_if_open(
        app,
        _GATETERM_USERS_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_USERS_CLOSE_DELAY_SECONDS", 0.8),
    )


def _close_gateterm_access_window_if_open(app: Any) -> None:
    _close_gateterm_window_if_open(
        app,
        _GATETERM_ACCESS_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_ACCESS_CLOSE_DELAY_SECONDS", 0.8),
    )


def _gateterm_dialog_windows(app: Any) -> list[Any]:
    dialogs: list[Any] = []
    for window in app.windows():
        try:
            window_title = str(window.window_text() or "").strip()
            class_name = str(window.class_name() or "").strip()
            if class_name == "ThunderRT6Main":
                continue
            if class_name == "#32770" or (window_title == "GateTerm" and class_name != "ThunderRT6FormDC"):
                dialogs.append(app.window(handle=window.handle))
        except Exception:
            continue
    return dialogs


def _click_gateterm_dialog_button(dialog: Any, *control_ids: int) -> bool:
    for control_id in control_ids:
        try:
            _click_gateterm_control(dialog, control_id, "Button", "ThunderRT6CommandButton")
            return True
        except Exception:
            continue
    return False


def _close_gateterm_message_boxes_if_open(app: Any) -> None:
    for _ in range(4):
        dialogs = _gateterm_dialog_windows(app)
        if not dialogs:
            return
        for dialog in dialogs:
            try:
                # Cleanup should discard stale unsaved changes, not cancel the dialog.
                if _click_gateterm_dialog_button(dialog, 7, 2, 1):
                    continue
                dialog.type_keys("%N")
            except Exception:
                try:
                    dialog.type_keys("{ESC}")
                except Exception:
                    continue
        time_module.sleep(_env_float("GATE_GATETERM_UI_MESSAGE_BOX_CLOSE_DELAY_SECONDS", 0.15))


def _confirm_gateterm_message_boxes_if_open(app: Any) -> None:
    for _ in range(4):
        dialogs = _gateterm_dialog_windows(app)
        if not dialogs:
            return
        for dialog in dialogs:
            try:
                if _click_gateterm_dialog_button(dialog, 6, 1):
                    continue
                dialog.type_keys("%Y")
            except Exception:
                try:
                    dialog.type_keys("{ENTER}")
                except Exception:
                    continue
        time_module.sleep(_env_float("GATE_GATETERM_UI_MESSAGE_BOX_CLOSE_DELAY_SECONDS", 0.15))


def _wait_for_gateterm_confirmation_dialog(app: Any, *, timeout_seconds: float) -> Any:
    deadline = time_module.monotonic() + max(0.0, timeout_seconds)
    while True:
        dialogs = _gateterm_dialog_windows(app)
        if dialogs:
            return dialogs[0]
        if time_module.monotonic() >= deadline:
            raise RuntimeError(f"GateTerm confirmation dialog did not appear; open windows: {_list_gateterm_windows(app)!r}")
        time_module.sleep(0.1)


def _confirm_gateterm_dialog(dialog: Any) -> None:
    if _click_gateterm_dialog_button(dialog, 6, 1):
        return
    try:
        dialog.type_keys("%Y")
    except Exception:
        dialog.type_keys("{ENTER}")


def _wait_for_gate_user_deleted(user_ptr: int, *, timeout_seconds: float) -> None:
    deadline = time_module.monotonic() + max(0.0, timeout_seconds)
    while True:
        with _readonly_cursor() as (_, cursor):
            row = cursor.execute(
                "SELECT TOP 1 UserPtr, Deleted FROM Users WHERE UserPtr = ?",
                (int(user_ptr),),
            ).fetchone()
            access_row = cursor.execute(
                "SELECT TOP 1 UserPtr FROM AccessTable WHERE UserPtr = ?",
                (int(user_ptr),),
            ).fetchone()
        if row is None or (bool(getattr(row, "Deleted", False)) and access_row is None):
            return
        if time_module.monotonic() >= deadline:
            raise RuntimeError(f"GateTerm did not delete key {int(user_ptr)}")
        time_module.sleep(0.25)


def _finalize_gateterm_user_edit_save(app: Any) -> None:
    _confirm_gateterm_message_boxes_if_open(app)
    time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_CONFIRM_DELAY_SECONDS", 0.35))
    if _window_still_open(app, _GATETERM_USER_EDIT_WINDOW_TITLE):
        try:
            _wait_for_gateterm_window_to_close(
                app,
                _GATETERM_USER_EDIT_WINDOW_TITLE,
                timeout_seconds=_env_float("GATE_GATETERM_UI_USER_SAVE_CLOSE_DELAY_SECONDS", 0.8),
            )
        except Exception:
            _close_gateterm_user_edit_window_if_open(app)


def _finalize_gateterm_vehicle_user_edit_save(app: Any) -> None:
    _confirm_gateterm_message_boxes_if_open(app)
    time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_CONFIRM_DELAY_SECONDS", 0.35))
    if _window_still_open(app, _GATETERM_USER_EDIT_WINDOW_TITLE):
        # Vehicle macro should finish with OK and the window close button; do not re-open/check the row.
        _close_gateterm_window_if_open(
            app,
            _GATETERM_USER_EDIT_WINDOW_TITLE,
            timeout_seconds=_env_float("GATE_GATETERM_UI_USER_EDIT_CLOSE_DELAY_SECONDS", 1.2),
        )


def _finalize_gateterm_new_user_save(app: Any) -> None:
    _confirm_gateterm_message_boxes_if_open(app)
    time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_CONFIRM_DELAY_SECONDS", 0.35))
    if _window_still_open(app, _GATETERM_NEW_USER_WINDOW_TITLE):
        try:
            _wait_for_gateterm_window_to_close(
                app,
                _GATETERM_NEW_USER_WINDOW_TITLE,
                timeout_seconds=_env_float("GATE_GATETERM_UI_USER_SAVE_CLOSE_DELAY_SECONDS", 0.8),
            )
        except Exception:
            _close_gateterm_new_user_window_if_open(app)


def _prepare_gateterm_users_workspace(app: Any) -> None:
    _close_gateterm_message_boxes_if_open(app)
    _close_gateterm_search_window_if_open(app)
    _close_gateterm_message_boxes_if_open(app)
    _close_gateterm_new_user_window_if_open(app)
    _close_gateterm_message_boxes_if_open(app)
    _close_gateterm_user_edit_window_if_open(app)
    _close_gateterm_message_boxes_if_open(app)
    _close_gateterm_users_window_if_open(app)
    _close_gateterm_message_boxes_if_open(app)


def _window_contains_vehicle_key(values: Iterable[Any], normalized_key_value: str) -> bool:
    for value in values:
        if _normalize_optional_text(value) == normalized_key_value:
            return True
    return False


def _collect_gateterm_window_values(window: Any) -> list[str]:
    values: list[str] = []
    try:
        values.extend(str(item or "") for item in window.texts())
    except Exception:
        pass

    try:
        descendants = window.descendants()
    except Exception:
        descendants = []

    for control in descendants:
        try:
            text_value = str(control.window_text() or "")
        except Exception:
            text_value = ""
        if text_value:
            values.append(text_value)
    return values


def _open_gateterm_users_view(app: Any) -> Any:
    refocus_deadline = time_module.time() + _env_float("GATE_GATETERM_UI_USERS_REFOCUS_DELAY_SECONDS", 0.5)
    while time_module.time() < refocus_deadline:
        users_window = _try_wait_for_gateterm_window(
            app,
            _GATETERM_USERS_WINDOW_TITLE,
            timeout_seconds=0.1,
        )
        if users_window is None:
            break
        try:
            if users_window.is_enabled():
                users_window.set_focus()
                return users_window
        except Exception:
            pass
        time_module.sleep(0.1)

    main_window = _find_gateterm_main_window(app)
    if main_window is None:
        raise RuntimeError(f"GATE main window is not open; open windows: {_list_gateterm_windows(app)!r}")
    main_window.set_focus()
    try:
        main_window.menu_select(_GATETERM_USERS_MENU_PATH)
    except Exception as menu_select_exc:
        try:
            menu = main_window.menu()
            if menu is None:
                raise RuntimeError("There is no menu.")
            items = menu.items()
            if len(items) < 2:
                raise RuntimeError(f"Unexpected menu structure: {len(items)} top-level items")
            submenu = items[1].sub_menu()
            if submenu is None:
                raise RuntimeError("Users menu submenu is missing.")
            subitems = submenu.items()
            if not subitems:
                raise RuntimeError("Users menu submenu has no items.")
            subitems[0].click()
        except Exception as menu_fallback_exc:
            raise RuntimeError(
                "GateTerm users view did not open via main menu; "
                f"menu_select_error={menu_select_exc}; menu_fallback_error={menu_fallback_exc}; "
                f"open windows={_list_gateterm_windows(app)!r}"
            ) from menu_fallback_exc
    users_window = _wait_for_enabled_gateterm_window(
        app,
        _GATETERM_USERS_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_USERS_OPEN_DELAY_SECONDS", 1.5),
    )
    users_window.set_focus()
    return users_window


def _open_gateterm_new_user_window(app: Any, users_window: Any) -> Any:
    dialog_delay_seconds = _env_float("GATE_GATETERM_UI_USER_EDIT_OPEN_DELAY_SECONDS", 0.9)
    attempts: list[str] = []

    users_window.set_focus()
    try:
        users_window.menu().items()[0].sub_menu().items()[0].click()
        attempts.append("menu")
    except Exception as exc:
        attempts.append(f"menu_error={exc}")
    new_user_window = _try_wait_for_gateterm_window(
        app,
        _GATETERM_NEW_USER_WINDOW_TITLE,
        timeout_seconds=dialog_delay_seconds,
    )
    if new_user_window is not None:
        return new_user_window

    # VB6 runtime errors (e.g. Error 91 "Object variable not set") produce an error
    # dialog instead of opening the new-user window.  Dismiss it now so the outer
    # retry loop gets a clean workspace on the next attempt.
    if _gateterm_dialog_windows(app):
        _close_gateterm_message_boxes_if_open(app)
        raise RuntimeError(
            "GateTerm error dialog appeared instead of new-user window (menu attempt); "
            f"attempts={attempts!r}; open windows={_list_gateterm_windows(app)!r}"
        )

    users_window.set_focus()
    try:
        users_window.type_keys("^n")
        attempts.append("hotkey")
    except Exception as exc:
        attempts.append(f"hotkey_error={exc}")
    new_user_window = _try_wait_for_gateterm_window(
        app,
        _GATETERM_NEW_USER_WINDOW_TITLE,
        timeout_seconds=dialog_delay_seconds,
    )
    if new_user_window is not None:
        return new_user_window

    # Same check for the hotkey attempt.
    if _gateterm_dialog_windows(app):
        _close_gateterm_message_boxes_if_open(app)
        raise RuntimeError(
            "GateTerm error dialog appeared instead of new-user window (hotkey attempt); "
            f"attempts={attempts!r}; open windows={_list_gateterm_windows(app)!r}"
        )

    raise RuntimeError(
        "GateTerm new-user window did not open; "
        f"attempts={attempts!r}; open windows={_list_gateterm_windows(app)!r}"
    )


def _open_gateterm_user_search_window(app: Any, users_window: Any) -> Any:
    dialog_delay_seconds = _env_float("GATE_GATETERM_UI_USER_SEARCH_DIALOG_DELAY_SECONDS", 0.5)
    attempts: list[str] = []

    users_window.set_focus()
    try:
        users_window.menu().items()[4].sub_menu().items()[0].click()
        attempts.append("menu")
    except Exception as exc:
        attempts.append(f"menu_error={exc}")
    search_window = _try_wait_for_gateterm_window(
        app,
        _GATETERM_USER_SEARCH_WINDOW_TITLE,
        timeout_seconds=dialog_delay_seconds,
    )
    if search_window is not None:
        return search_window

    users_window.set_focus()
    try:
        users_window.type_keys("^f")
        attempts.append("hotkey")
    except Exception as exc:
        attempts.append(f"hotkey_error={exc}")
    search_window = _try_wait_for_gateterm_window(
        app,
        _GATETERM_USER_SEARCH_WINDOW_TITLE,
        timeout_seconds=dialog_delay_seconds,
    )
    if search_window is not None:
        return search_window

    raise RuntimeError(
        "GateTerm user-search window did not open; "
        f"attempts={attempts!r}; open windows={_list_gateterm_windows(app)!r}"
    )


def _search_gateterm_user_by_key_number(app: Any, users_window: Any, normalized_key_value: str) -> None:
    search_window = _open_gateterm_user_search_window(app, users_window)

    combo = _visible_gateterm_control_by_id(search_window, 4, "ThunderRT6ComboBox", "ComboBox")
    edit = _visible_gateterm_control_by_id(search_window, 3, "ThunderRT6TextBox", "Edit")
    try:
        combo.select(_GATETERM_USER_SEARCH_FIELD_KEY_NUMBER_INDEX)
    except Exception:
        combo.select(_GATETERM_USER_SEARCH_FIELD_KEY_NUMBER)

    try:
        edit.set_focus()
        if hasattr(edit, "set_edit_text"):
            edit.set_edit_text(normalized_key_value)
        else:
            edit.type_keys("^a{BACKSPACE}")
            edit.type_keys(normalized_key_value, with_spaces=True, set_foreground=True)
    except Exception as exc:
        raise RuntimeError(f"GateTerm user search input failed: {exc}") from exc

    time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SEARCH_APPLY_DELAY_SECONDS", 0.35))

    try:
        _click_gateterm_control(search_window, 5, "ThunderRT6CommandButton", "Button")
    except Exception:
        if _window_still_open(app, _GATETERM_USER_SEARCH_WINDOW_TITLE):
            _dismiss_gateterm_window_via_escape(app, _GATETERM_USER_SEARCH_WINDOW_TITLE)
    if not _window_still_open(app, _GATETERM_USER_SEARCH_WINDOW_TITLE):
        return
    _wait_for_gateterm_window_to_close(
        app,
        _GATETERM_USER_SEARCH_WINDOW_TITLE,
        timeout_seconds=_env_float("GATE_GATETERM_UI_USER_SEARCH_CLOSE_DELAY_SECONDS", 0.8),
    )


def _set_gateterm_text_input(control: Any, value: str, *, field_name: str) -> None:
    try:
        control.set_focus()
        if hasattr(control, "set_edit_text"):
            control.set_edit_text(value)
        else:
            control.type_keys("^a{BACKSPACE}")
            control.type_keys(value, with_spaces=True, set_foreground=True)
        # GateTerm commits the key-number edit only after the field loses focus.
        if hasattr(control, "type_keys"):
            control.type_keys("{TAB}")
    except Exception as exc:
        raise RuntimeError(f"GateTerm {field_name} input failed: {exc}") from exc



def _set_gateterm_combo_value(control: Any, value: str, *, field_name: str) -> None:
    try:
        control.select(value)
    except Exception as exc:
        raise RuntimeError(f"GateTerm {field_name} selection failed: {exc}") from exc
    time_module.sleep(_env_float("GATE_GATETERM_UI_COMBO_COMMIT_DELAY_SECONDS", 0.2))


def _set_gateterm_checkbox_state(control: Any, desired_state: bool, *, field_name: str) -> None:
    try:
        current_state = bool(control.get_check_state())
    except Exception as exc:
        raise RuntimeError(f"GateTerm {field_name} state read failed: {exc}") from exc
    if current_state == bool(desired_state):
        return
    try:
        control.click()
    except Exception:
        control.click_input()
    time_module.sleep(_env_float("GATE_GATETERM_UI_CHECKBOX_TOGGLE_DELAY_SECONDS", 0.15))
    try:
        updated_state = bool(control.get_check_state())
    except Exception as exc:
        raise RuntimeError(f"GateTerm {field_name} state verify failed: {exc}") from exc
    if updated_state != bool(desired_state):
        raise RuntimeError(
            f"GateTerm {field_name} did not reach the requested state {bool(desired_state)!r}"
        )


def _set_gateterm_user_key_number(edit_window: Any, normalized_key_value: str) -> None:
    # Live GateTerm user dialog keeps the visible editable key-number textbox
    # on a stable control id even when the label text is not exposed to pywinauto.
    commit_delay_seconds = _env_float("GATE_GATETERM_UI_KEY_NUMBER_COMMIT_DELAY_SECONDS", 1.0)
    try:
        direct_edit = _visible_gateterm_control_by_id(edit_window, 88, "ThunderRT6TextBox", "Edit")
    except Exception:
        direct_edit = None
    if direct_edit is not None:
        _set_gateterm_text_input(
            direct_edit,
            normalized_key_value,
            field_name=f"user key number {_GATETERM_USER_SEARCH_FIELD_KEY_NUMBER!r}",
        )
        time_module.sleep(commit_delay_seconds)
        return

    try:
        descendants = edit_window.descendants()
    except Exception as exc:
        raise RuntimeError(f"GateTerm key-number field lookup failed: {exc}") from exc

    visible_controls: list[Any] = []
    for control in descendants:
        try:
            wrapper = control.wrapper_object()
        except Exception:
            wrapper = control
        try:
            if not wrapper.is_visible():
                continue
        except Exception:
            pass
        visible_controls.append(wrapper)

    normalized_label = str(_GATETERM_USER_SEARCH_FIELD_KEY_NUMBER or "").strip().casefold()
    edit_classes = {"ThunderRT6TextBox", "Edit"}
    labeled_edit: Any | None = None

    for index, control in enumerate(visible_controls):
        try:
            control_text = str(control.window_text() or "").strip().casefold()
        except Exception:
            control_text = ""
        if control_text != normalized_label:
            continue
        for candidate in visible_controls[index + 1 :]:
            try:
                class_name = str(candidate.class_name() or "")
            except Exception:
                class_name = ""
            if class_name in edit_classes:
                labeled_edit = candidate
                break
        if labeled_edit is not None:
            break

    if labeled_edit is None:
        edits: list[Any] = []
        for control in visible_controls:
            try:
                class_name = str(control.class_name() or "")
            except Exception:
                class_name = ""
            if class_name in edit_classes:
                edits.append(control)
        if len(edits) == 1:
            labeled_edit = edits[0]

    if labeled_edit is None:
        raise RuntimeError(
            f"GateTerm key-number field {_GATETERM_USER_SEARCH_FIELD_KEY_NUMBER!r} was not found in the user edit dialog"
        )

    _set_gateterm_text_input(
        labeled_edit,
        normalized_key_value,
        field_name=f"user key number {_GATETERM_USER_SEARCH_FIELD_KEY_NUMBER!r}",
    )
    time_module.sleep(commit_delay_seconds)


def _read_gateterm_user_key_number(edit_window: Any) -> str:
    _select_gateterm_user_editor_tab(edit_window, "key")
    control = _visible_gateterm_control_by_id(edit_window, 88, "ThunderRT6TextBox", "Edit")
    value = str(control.window_text() or "").strip()
    if value:
        return value
    texts = [str(item or "").strip() for item in control.texts()]
    for text_value in texts:
        if text_value:
            return text_value
    raise RuntimeError("GateTerm user key number is empty in the edit dialog")


def _first_visible_gateterm_tab_control(window: Any) -> Any:
    for control in window.descendants():
        try:
            if str(control.class_name() or "") != "SSTabCtlWndClass":
                continue
            rect = control.rectangle()
            if rect.left <= 0:
                continue
            return control
        except Exception:
            continue
    raise RuntimeError(f"GateTerm tab control was not found in {window.window_text()!r}")


def _select_gateterm_user_editor_tab(window: Any, tab_name: str) -> None:
    offset_x = _GATETERM_USER_EDITOR_TAB_OFFSETS.get(tab_name)
    if offset_x is None:
        raise RuntimeError(f"Unsupported GateTerm editor tab: {tab_name}")
    tab_control = _first_visible_gateterm_tab_control(window)
    rect = tab_control.rectangle()
    height = max(1, rect.bottom - rect.top)
    tab_control.click_input(coords=(offset_x, max(1, height - 10)))
    time_module.sleep(_env_float("GATE_GATETERM_UI_TAB_SWITCH_DELAY_SECONDS", 0.35))


def _canonical_gateterm_access_label(value: Any) -> str:
    normalized = " ".join(str(value or "").strip().casefold().split())
    if not normalized:
        return ""
    if "север" in normalized:
        return "северная калитка"
    if "калитка 1" in normalized:
        return "калитка 1"
    if "озер" in normalized:
        return "калитка озеро"
    if "лес" in normalized:
        return "калитка лес"
    if "камера" in normalized and "въезд" in normalized:
        return "камера въезда"
    if "камера" in normalized and "выезд" in normalized:
        return "камера выезда"
    if "gsm" in normalized and "въезд" in normalized:
        return "считыватель въезд gsm"
    if "gsm" in normalized and "выезд" in normalized:
        return "считыватель выезд gsm"
    if "транспондер" in normalized and "въезд" in normalized:
        return "транспондер въезд"
    if "транспондер" in normalized and "выезд" in normalized:
        return "транспондер выезд"
    if normalized.startswith("считыватель "):
        normalized = normalized[len("считыватель ") :]
    if normalized.startswith("вход "):
        normalized = normalized[len("вход ") :]
    return normalized


def _resolve_gateterm_access_labels(
    cursor: pyodbc.Cursor,
    access_point_ids: Iterable[int],
) -> set[str]:
    desired_labels: set[str] = set()
    for point_id in access_point_ids:
        row = cursor.execute(
            """
            SELECT TOP 1 Name
            FROM Readers
            WHERE RdrPtr = ?
            """,
            (int(point_id),),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Gate reader {int(point_id)} is not found for GateTerm access mapping")
        label = _canonical_gateterm_access_label(getattr(row, "Name", None))
        if not label:
            raise RuntimeError(f"Gate reader {int(point_id)} has no usable name for GateTerm access mapping")
        desired_labels.add(label)
    return desired_labels


def _load_phone_ui_provisioning_context(
    *,
    normalized_key_value: str,
    access_point_ids: Iterable[int],
) -> dict[str, Any]:
    with _readonly_cursor() as (_, cursor):
        phone_key_type_value = _sample_key_type(cursor, "Phone", access_point_ids)
        existing_user_ptr = _find_existing_user_ptr(
            cursor,
            "Phone",
            normalized_key_value,
            key_type_value=phone_key_type_value,
        )
        phone_storage_value = _format_phone_for_storage(cursor, normalized_key_value)
        desired_access_labels = _resolve_gateterm_access_labels(cursor, access_point_ids)
        current_access_labels: set[str] = set()
        if existing_user_ptr is not None:
            access_rows = cursor.execute(
                """
                SELECT RdrPtr
                FROM AccessTable
                WHERE UserPtr = ?
                ORDER BY RdrPtr
                """,
                (int(existing_user_ptr),),
            ).fetchall()
            current_access_labels = _resolve_gateterm_access_labels(
                cursor,
                [
                    int(getattr(item, "RdrPtr", item[0]))
                    for item in access_rows
                ],
            )
    return {
        "existing_user_ptr": existing_user_ptr,
        "phone_key_type_value": phone_key_type_value,
        "phone_storage_value": phone_storage_value,
        "desired_access_labels": desired_access_labels,
        "current_access_labels": current_access_labels,
    }


def _load_vehicle_ui_provisioning_context(
    *,
    normalized_key_value: str,
    access_point_ids: Iterable[int],
) -> dict[str, Any]:
    with _readonly_cursor() as (_, cursor):
        vehicle_key_type_value = _sample_key_type(cursor, "VehicleNumber", access_point_ids)
        existing_user_ptr = _find_existing_user_ptr(
            cursor,
            "VehicleNumber",
            normalized_key_value,
            key_type_value=vehicle_key_type_value,
        )
        desired_access_labels = _resolve_gateterm_access_labels(cursor, access_point_ids)
        current_access_labels: set[str] = set()
        if existing_user_ptr is not None:
            access_rows = cursor.execute(
                "SELECT RdrPtr FROM AccessTable WHERE UserPtr = ? ORDER BY RdrPtr",
                (int(existing_user_ptr),),
            ).fetchall()
            current_access_labels = _resolve_gateterm_access_labels(
                cursor,
                [int(getattr(r, "RdrPtr", r[0])) for r in access_rows],
            )
    return {
        "existing_user_ptr": existing_user_ptr,
        "vehicle_key_type_value": vehicle_key_type_value,
        "desired_access_labels": desired_access_labels,
        "current_access_labels": current_access_labels,
    }


def _lb_getitemdata(hwnd: int, index: int) -> int:
    """Return the check state of a VB6 CheckListBox item via Win32 LB_GETITEMDATA.

    Returns 0 (unchecked), 1 (checked), 2 (grayed), or -1 (LB_ERR / error).
    """
    import ctypes
    LB_GETITEMDATA = 0x0199
    return ctypes.windll.user32.SendMessageW(hwnd, LB_GETITEMDATA, index, 0)


def _configure_gateterm_phone_access_permissions(
    window: Any,
    *,
    desired_access_labels: set[str],
    current_access_labels: set[str],
) -> None:
    _select_gateterm_user_editor_tab(window, "access")
    listbox = _visible_gateterm_control_by_id(window, 39, "ThunderRT6ListBox", "ListBox")

    try:
        item_texts = [str(item or "") for item in listbox.item_texts()]
    except Exception as exc:
        raise RuntimeError(f"GateTerm access list lookup failed: {exc}") from exc
    if not item_texts:
        raise RuntimeError("GateTerm access list is empty")

    available_labels = {_canonical_gateterm_access_label(item) for item in item_texts}
    missing_labels = sorted(label for label in desired_access_labels if label not in available_labels)
    if missing_labels:
        raise RuntimeError(
            "GateTerm access list is missing expected readers: "
            f"{missing_labels!r}; available={sorted(available_labels)!r}"
        )

    # Read actual checked state from the UI rather than relying on DB state.
    # For new users, DB state is empty while GateTerm may start with all items checked —
    # using DB-based symmetric_difference would produce a wrong toggle set in that case.
    try:
        hwnd = int(listbox.handle)
        actual_checked_labels: set[str] = set()
        for index, item_text in enumerate(item_texts):
            data = _lb_getitemdata(hwnd, index)
            if data == 1:
                actual_checked_labels.add(_canonical_gateterm_access_label(item_text))
        toggle_labels = desired_access_labels.symmetric_difference(actual_checked_labels)
    except Exception:
        toggle_labels = desired_access_labels.symmetric_difference(current_access_labels)

    if not toggle_labels:
        return

    checkbox_offset_x = _env_int("GATE_GATETERM_UI_ACCESS_CHECKBOX_X", 8)
    for index, item_text in enumerate(item_texts):
        current_label = _canonical_gateterm_access_label(item_text)
        if current_label not in toggle_labels:
            continue
        item_rect = listbox.item_rect(index)
        click_y = int(item_rect.top + max(4, (item_rect.bottom - item_rect.top) // 2))
        listbox.click_input(coords=(checkbox_offset_x, click_y))
        time_module.sleep(_env_float("GATE_GATETERM_UI_ACCESS_TOGGLE_DELAY_SECONDS", 0.2))


def _populate_gateterm_phone_pass_editor(
    window: Any,
    *,
    normalized_key_value: str,
    phone_storage_value: str,
    resident_name: str,
    plot_number: str | None,
    desired_access_labels: set[str],
    current_access_labels: set[str],
) -> None:
    last_name, first_name, father_name = _split_name(resident_name)
    _set_gateterm_text_input(
        _visible_gateterm_control_by_id(window, 8, "ThunderRT6TextBox", "Edit"),
        str(last_name or ""),
        field_name="resident last name",
    )
    _set_gateterm_text_input(
        _visible_gateterm_control_by_id(window, 7, "ThunderRT6TextBox", "Edit"),
        str(first_name or ""),
        field_name="resident first name",
    )
    _set_gateterm_text_input(
        _visible_gateterm_control_by_id(window, 6, "ThunderRT6TextBox", "Edit"),
        str(father_name or ""),
        field_name="resident father name",
    )
    _set_gateterm_combo_value(
        _visible_gateterm_control_by_id(window, 10, "ThunderRT6ComboBox", "ComboBox"),
        "GSM",
        field_name="resident group",
    )
    _set_gateterm_checkbox_state(
        _visible_gateterm_control_by_id(window, 4, "ThunderRT6CheckBox", "Button"),
        False,
        field_name="resident visitor flag",
    )

    _select_gateterm_user_editor_tab(window, "key")
    _set_gateterm_combo_value(
        _visible_gateterm_control_by_id(window, 83, "ThunderRT6ComboBox", "ComboBox"),
        "Wiegand-48",
        field_name="phone key type",
    )
    _set_gateterm_checkbox_state(
        _visible_gateterm_control_by_id(window, 81, "ThunderRT6CheckBox", "Button"),
        False,
        field_name="phone key facility embedding",
    )
    _set_gateterm_user_key_number(window, normalized_key_value)

    _select_gateterm_user_editor_tab(window, "info")
    _set_gateterm_text_input(
        _visible_gateterm_control_by_id(window, 68, "ThunderRT6TextBox", "Edit"),
        str(_normalize_gate_detail(plot_number) or ""),
        field_name="resident plot number",
    )
    _set_gateterm_text_input(
        _visible_gateterm_control_by_id(window, 66, "ThunderRT6TextBox", "Edit"),
        phone_storage_value,
        field_name="resident phone",
    )
    _set_gateterm_checkbox_state(
        _visible_gateterm_control_by_id(window, 67, "ThunderRT6CheckBox", "Button"),
        False,
        field_name="SMS notifications",
    )
    _set_gateterm_checkbox_state(
        _visible_gateterm_control_by_id(window, 64, "ThunderRT6CheckBox", "Button"),
        False,
        field_name="E-Mail notifications",
    )

    _configure_gateterm_phone_access_permissions(
        window,
        desired_access_labels=desired_access_labels,
        current_access_labels=current_access_labels,
    )


def _populate_gateterm_vehicle_pass_editor(
    window: Any,
    *,
    normalized_key_value: str,
    resident_name: str | None,
    plot_number: str | None = None,
    phone_number: str | None = None,
    desired_access_labels: set[str] | None = None,
    current_access_labels: set[str] | None = None,
) -> None:
    normalized_resident_name = _compose_gate_user_name(resident_name)
    if normalized_resident_name is not None:
        last_name, first_name, father_name = _split_name(normalized_resident_name)
        _set_gateterm_text_input(
            _visible_gateterm_control_by_id(window, 8, "ThunderRT6TextBox", "Edit"),
            str(last_name or ""),
            field_name="resident last name",
        )
        _set_gateterm_text_input(
            _visible_gateterm_control_by_id(window, 7, "ThunderRT6TextBox", "Edit"),
            str(first_name or ""),
            field_name="resident first name",
        )
        _set_gateterm_text_input(
            _visible_gateterm_control_by_id(window, 6, "ThunderRT6TextBox", "Edit"),
            str(father_name or ""),
            field_name="resident father name",
        )
    _set_gateterm_combo_value(
        _visible_gateterm_control_by_id(window, 10, "ThunderRT6ComboBox", "ComboBox"),
        "Группа",
        field_name="resident group",
    )
    _set_gateterm_checkbox_state(
        _visible_gateterm_control_by_id(window, 4, "ThunderRT6CheckBox", "Button"),
        False,
        field_name="resident visitor flag",
    )

    _select_gateterm_user_editor_tab(window, "key")
    _set_gateterm_combo_value(
        _visible_gateterm_control_by_id(window, 83, "ThunderRT6ComboBox", "ComboBox"),
        "Номер ТС",
        field_name="vehicle key type",
    )
    _set_gateterm_checkbox_state(
        _visible_gateterm_control_by_id(window, 81, "ThunderRT6CheckBox", "Button"),
        False,
        field_name="vehicle key facility embedding",
    )
    latin_key_value = _normalize_vehicle(normalized_key_value)
    _set_gateterm_text_input(
        _visible_gateterm_control_by_id(window, 88, "ThunderRT6TextBox", "Edit"),
        latin_key_value,
        field_name="vehicle key number",
    )

    if plot_number is not None or phone_number is not None:
        _select_gateterm_user_editor_tab(window, "info")
        if plot_number is not None:
            _set_gateterm_text_input(
                _visible_gateterm_control_by_id(window, 68, "ThunderRT6TextBox", "Edit"),
                str(_normalize_gate_detail(plot_number) or ""),
                field_name="resident plot number",
            )
        if phone_number is not None:
            _set_gateterm_text_input(
                _visible_gateterm_control_by_id(window, 66, "ThunderRT6TextBox", "Edit"),
                str(_normalize_contact_phone(phone_number) or ""),
                field_name="resident contact phone",
            )

    if desired_access_labels:
        _configure_gateterm_phone_access_permissions(
            window,
            desired_access_labels=desired_access_labels,
            current_access_labels=current_access_labels or set(),
        )


def _restore_gate_user_name_fields(*, user_ptr: int, resident_name: str | None) -> None:
    normalized_resident_name = _compose_gate_user_name(resident_name)
    if normalized_resident_name is None:
        return

    with _transaction_cursor() as (_, cursor):
        _set_gate_user_name_fields(cursor, user_ptr=int(user_ptr), resident_name=normalized_resident_name)


def _open_gateterm_user_edit_window(app: Any, users_window: Any) -> Any:
    dialog_delay_seconds = _env_float("GATE_GATETERM_UI_USER_EDIT_OPEN_DELAY_SECONDS", 0.9)
    attempts: list[str] = []

    users_window.set_focus()
    try:
        users_window.menu().items()[0].sub_menu().items()[1].click()
        attempts.append("menu")
    except Exception as exc:
        attempts.append(f"menu_error={exc}")
    edit_window = _try_wait_for_gateterm_window(
        app,
        _GATETERM_USER_EDIT_WINDOW_TITLE,
        timeout_seconds=dialog_delay_seconds,
    )
    if edit_window is not None:
        return edit_window

    users_window.set_focus()
    try:
        users_window.type_keys("^e")
        attempts.append("hotkey")
    except Exception as exc:
        attempts.append(f"hotkey_error={exc}")
    edit_window = _try_wait_for_gateterm_window(
        app,
        _GATETERM_USER_EDIT_WINDOW_TITLE,
        timeout_seconds=dialog_delay_seconds,
    )
    if edit_window is not None:
        return edit_window

    raise RuntimeError(
        "GateTerm user-edit window did not open; "
        f"attempts={attempts!r}; open windows={_list_gateterm_windows(app)!r}"
    )


def _verify_gateterm_selected_user_key_number(app: Any, users_window: Any, normalized_key_value: str) -> None:
    edit_window = _open_gateterm_user_edit_window(app, users_window)
    try:
        actual_key_number = _read_gateterm_user_key_number(edit_window)
    finally:
        _close_gateterm_user_edit_window_if_open(app)
    if actual_key_number != normalized_key_value:
        raise RuntimeError(
            "GateTerm search selected an unexpected user; "
            f"expected key number {normalized_key_value!r}, got {actual_key_number!r}"
        )


def _verify_vehicle_identity_persisted(
    user_ptr: int,
    normalized_key_value: str,
    expected_number_u: str | None,
    *,
    expected_resident_name: str | None = None,
) -> None:
    with _readonly_cursor() as (_, cursor):
        has_display_name = _users_has_display_name_column(cursor)
        display_name_column = "[Name] AS DisplayName," if has_display_name else ""
        row = cursor.execute(
            f"""
            SELECT TOP 1 Number, NumberU, {display_name_column}
                   LastName, FirstName, FatherName
            FROM Users
            WHERE UserPtr = ?
            """,
            (int(user_ptr),),
        ).fetchone()

    if row is None:
        raise RuntimeError(f"Gate vehicle key {user_ptr} disappeared after GateTerm post-sync")

    normalized_number = _normalize_optional_text(getattr(row, "Number", None))
    actual_number_u_raw = getattr(row, "NumberU", None)
    normalized_number_u = _normalize_optional_text(actual_number_u_raw)
    actual_number_u = str(actual_number_u_raw or "").strip()
    expected_number_u_normalized = _normalize_optional_text(expected_number_u)
    if normalized_number != normalized_key_value:
        raise RuntimeError(
            "GateTerm vehicle post-sync changed Users.Number unexpectedly; "
            f"expected={normalized_key_value!r}, actual={getattr(row, 'Number', None)!r}, UserPtr={user_ptr}"
        )
    if not normalized_number_u:
        raise RuntimeError(
            "GateTerm vehicle post-sync left Users.NumberU empty; "
            f"Number={normalized_key_value!r}, UserPtr={user_ptr}"
        )
    expected_full_name = _compose_gate_user_name(expected_resident_name)
    if expected_full_name is not None:
        actual_full_name = _gate_row_resident_name(row)
        if actual_full_name != expected_full_name:
            raise RuntimeError(
                "GateTerm vehicle post-sync changed resident name unexpectedly; "
                f"expected={expected_full_name!r}, actual={actual_full_name!r}, UserPtr={user_ptr}"
            )
        if has_display_name:
            actual_display_name = _normalize_gate_detail(getattr(row, "DisplayName", getattr(row, "Name", None)))
            if actual_display_name != expected_full_name:
                raise RuntimeError(
                    "GateTerm vehicle post-sync changed Users.Name unexpectedly; "
                    f"expected={expected_full_name!r}, actual={actual_display_name!r}, UserPtr={user_ptr}"
                )
    if expected_number_u_normalized:
        if actual_number_u == str(expected_number_u or "").strip():
            return
        raise RuntimeError(
            "GateTerm vehicle post-sync changed Users.NumberU unexpectedly; "
            f"expected={expected_number_u!r}, actual={actual_number_u_raw!r}, UserPtr={user_ptr}"
        )
    if actual_number_u != normalized_key_value:
        return
    raise RuntimeError(
        "GateTerm vehicle post-sync did not materialize an internal Users.NumberU value; "
        f"NumberU stayed equal to the vehicle number {normalized_key_value!r} for UserPtr={user_ptr}"
    )


def _verify_phone_identity_persisted(
    user_ptr: int,
    normalized_key_value: str,
    phone_key_type_value: Any | None,
    access_point_ids: Iterable[int],
) -> None:
    with _readonly_cursor() as (_, cursor):
        _verify_phone_user_state(
            cursor,
            user_ptr=int(user_ptr),
            normalized_key_value=normalized_key_value,
            phone_key_type_value=phone_key_type_value,
            access_point_ids=access_point_ids,
        )


def _wait_for_phone_user_ptr(
    *,
    normalized_key_value: str,
    phone_key_type_value: Any | None,
    timeout_seconds: float,
) -> int:
    deadline = time_module.monotonic() + max(timeout_seconds, 0.0)
    while True:
        with _readonly_cursor() as (_, cursor):
            user_ptr = _find_existing_user_ptr(
                cursor,
                "Phone",
                normalized_key_value,
                key_type_value=phone_key_type_value,
            )
        if user_ptr is not None:
            return int(user_ptr)
        if time_module.monotonic() >= deadline:
            raise RuntimeError(f"GateTerm did not materialize phone key {normalized_key_value!r} in time")
        time_module.sleep(_env_float("GATE_GATETERM_UI_CREATE_VERIFY_POLL_SECONDS", 0.5))


def _wait_for_vehicle_user_ptr(
    *,
    normalized_key_value: str,
    vehicle_key_type_value: Any | None,
    timeout_seconds: float,
) -> int:
    deadline = time_module.monotonic() + max(timeout_seconds, 0.0)
    while True:
        with _readonly_cursor() as (_, cursor):
            user_ptr = _find_existing_user_ptr(
                cursor,
                "VehicleNumber",
                normalized_key_value,
                key_type_value=vehicle_key_type_value,
            )
        if user_ptr is not None:
            return int(user_ptr)
        if time_module.monotonic() >= deadline:
            raise RuntimeError(f"GateTerm did not materialize vehicle key {normalized_key_value!r} in time")
        time_module.sleep(_env_float("GATE_GATETERM_UI_CREATE_VERIFY_POLL_SECONDS", 0.5))


def _post_sync_phone_key_via_gateterm_ui(
    *,
    user_ptr: int,
    normalized_key_value: str,
    phone_key_type_value: Any | None,
    access_point_ids: Iterable[int],
) -> dict[str, Any]:
    try:
        from pywinauto import Application
    except ImportError as exc:
        raise RuntimeError(f"pywinauto is required for GateTerm phone post-sync: {exc}") from exc

    gate_term_exe = _env("GATE_GATETERM_EXE", default=r"C:\GATE\Terminal\GateTerm.exe")
    if not gate_term_exe:
        raise RuntimeError("GATE_GATETERM_EXE is not configured")

    attempts = max(1, _env_int("GATE_GATETERM_UI_POST_SYNC_ATTEMPTS", 3))
    last_error: Exception | None = None
    for attempt_index in range(attempts):
        try:
            app = Application(backend="win32").connect(path=gate_term_exe)
            _prepare_gateterm_users_workspace(app)
            users_window = _open_gateterm_users_view(app)
            _search_gateterm_user_by_key_number(app, users_window, normalized_key_value)
            edit_window = _open_gateterm_user_edit_window(app, users_window)

            editor_values = _collect_gateterm_window_values(edit_window)
            if not _window_contains_vehicle_key(editor_values, normalized_key_value):
                raise RuntimeError(
                    "GateTerm edit dialog did not open the expected phone key: "
                    f"expected {normalized_key_value!r}, got {editor_values!r}"
                )

            _set_gateterm_user_key_number(edit_window, normalized_key_value)
            _click_gateterm_control(edit_window, 1, "ThunderRT6CommandButton", "Button")
            time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_DELAY_SECONDS", 0.75))
            _finalize_gateterm_user_edit_save(app)
            _verify_phone_identity_persisted(user_ptr, normalized_key_value, phone_key_type_value, access_point_ids)
            _close_gateterm_users_window_if_open(app)
            break
        except Exception as exc:
            last_error = exc
            try:
                app = Application(backend="win32").connect(path=gate_term_exe)
                _prepare_gateterm_users_workspace(app)
            except Exception:
                pass
            if attempt_index + 1 >= attempts:
                raise RuntimeError(f"GateTerm phone post-sync failed: {exc}") from exc
            time_module.sleep(_env_float("GATE_GATETERM_UI_RETRY_DELAY_SECONDS", 0.35))

    if last_error is not None and attempts < 1:
        raise RuntimeError(f"GateTerm phone post-sync failed: {last_error}") from last_error

    return {
        "transport": "gateterm_ui",
        "user_ptr": int(user_ptr),
        "key_value": normalized_key_value,
    }


def _post_sync_vehicle_key_via_gateterm_ui(
    *,
    user_ptr: int,
    normalized_key_value: str,
    expected_number_u: str | None,
    resident_name: str | None,
) -> dict[str, Any]:
    try:
        from pywinauto import Application
    except ImportError as exc:
        raise RuntimeError(f"pywinauto is required for GateTerm vehicle post-sync: {exc}") from exc

    gate_term_exe = _env("GATE_GATETERM_EXE", default=r"C:\GATE\Terminal\GateTerm.exe")
    if not gate_term_exe:
        raise RuntimeError("GATE_GATETERM_EXE is not configured")

    attempts = max(1, _env_int("GATE_GATETERM_UI_POST_SYNC_ATTEMPTS", 3))
    last_error: Exception | None = None
    for attempt_index in range(attempts):
        try:
            app = Application(backend="win32").connect(path=gate_term_exe)
            _prepare_gateterm_users_workspace(app)
            users_window = _open_gateterm_users_view(app)
            _search_gateterm_user_by_key_number(app, users_window, normalized_key_value)
            edit_window = _open_gateterm_user_edit_window(app, users_window)

            editor_values = _collect_gateterm_window_values(edit_window)
            if not _window_contains_vehicle_key(editor_values, normalized_key_value):
                raise RuntimeError(
                    "GateTerm edit dialog did not open the expected vehicle key: "
                    f"expected {normalized_key_value!r}, got {editor_values!r}"
                )

            _populate_gateterm_vehicle_pass_editor(
                edit_window,
                normalized_key_value=normalized_key_value,
                resident_name=resident_name,
            )
            _click_gateterm_control(edit_window, 1, "ThunderRT6CommandButton", "Button")
            time_module.sleep(_env_float("GATE_GATETERM_UI_USER_SAVE_DELAY_SECONDS", 0.75))
            _finalize_gateterm_vehicle_user_edit_save(app)
            _restore_gate_user_name_fields(user_ptr=user_ptr, resident_name=resident_name)
            _close_gateterm_users_window_if_open(app)
            break
        except Exception as exc:
            last_error = exc
            try:
                app = Application(backend="win32").connect(path=gate_term_exe)
                _prepare_gateterm_users_workspace(app)
            except Exception:
                pass
            if attempt_index + 1 >= attempts:
                raise RuntimeError(f"GateTerm vehicle post-sync failed: {exc}") from exc
            time_module.sleep(_env_float("GATE_GATETERM_UI_RETRY_DELAY_SECONDS", 0.35))

    if last_error is not None and attempts < 1:
        raise RuntimeError(f"GateTerm vehicle post-sync failed: {last_error}") from last_error

    return {
        "transport": "gateterm_ui",
        "user_ptr": int(user_ptr),
        "key_value": normalized_key_value,
    }


def _gateterm_ui_row_override() -> dict[int, int]:
    raw = _env("GATE_GATETERM_UI_ROW_MAP_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    resolved: dict[int, int] = {}
    for key, value in parsed.items():
        try:
            resolved[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return resolved


def _gateterm_ui_visible_rows(cursor: pyodbc.Cursor) -> list[dict[str, Any]]:
    rows = cursor.execute(
        """
        SELECT
            r.RdrPtr,
            r.Num,
            r.Name AS ReaderName,
            d.DevPtr,
            d.PortPtr,
            d.Address,
            d.Name AS DeviceName,
            d.DevMode,
            d.AutoNumbers,
            d.Dinner
        FROM Readers AS r
        INNER JOIN Devices AS d ON d.DevPtr = r.DevPtr
        ORDER BY d.DevPtr, r.Num
        """
    ).fetchall()

    visible_rows: list[dict[str, Any]] = []
    for row in rows:
        try:
            reader_num = int(row.Num)
        except (TypeError, ValueError):
            continue
        if bool(getattr(row, "Dinner", False)):
            continue

        dev_mode = int(getattr(row, "DevMode", 0) or 0)
        auto_numbers = bool(getattr(row, "AutoNumbers", False))
        if reader_num != 1 and dev_mode == 1:
            continue

        visible_rows.append(
            {
                "access_point_id": int(row.RdrPtr),
                "reader_num": reader_num,
                "reader_name": str(row.ReaderName or ""),
                "device_id": int(row.DevPtr),
                "device_address": int(row.Address),
                "device_name": str(row.DeviceName or ""),
                "dev_mode": dev_mode,
                "auto_numbers": auto_numbers,
            }
        )
    return visible_rows


def _current_gate_events_db_path() -> Path:
    mdb_path, _ = _resolve_gate_paths()
    return mdb_path.parent / "Events" / f"n{datetime.now():%y%m%d}.mdb"


def _latest_gate_open_event(access_point_id: int) -> dict[str, Any] | None:
    events_db = _current_gate_events_db_path()
    if not events_db.exists():
        return None

    _, systemdb_path = _resolve_gate_paths()
    temp_dir = Path(tempfile.mkdtemp(prefix="gate-event-ro-"))
    temp_events = temp_dir / events_db.name
    temp_systemdb = temp_dir / "Gate.mdw"
    try:
        shutil.copy2(events_db, temp_events)
        shutil.copy2(systemdb_path, temp_systemdb)
        conn = pyodbc.connect(_build_connection_string(temp_events, temp_systemdb))
        cursor = conn.cursor()
        try:
            row = cursor.execute(
                """
                SELECT TOP 1
                    [Index],
                    [DateTime],
                    EventType,
                    EventCode,
                    DevPtr,
                    RdrPtr,
                    OperatorID,
                    Unit,
                    Message,
                    [Name]
                FROM Events
                WHERE RdrPtr = ?
                  AND EventType = 5
                  AND EventCode = 208
                ORDER BY [Index] DESC
                """,
                (access_point_id,),
            ).fetchone()
        finally:
            cursor.close()
            conn.close()
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    if row is None:
        return None
    event_time = row[1]
    return {
        "index": int(row[0]),
        "time": event_time.isoformat() if isinstance(event_time, datetime) else str(event_time),
        "event_type": int(row[2]),
        "event_code": int(row[3]),
        "device_id": int(row[4]),
        "access_point_id": int(row[5]),
        "operator_id": int(row[6]),
        "unit": str(row[7] or ""),
        "message": str(row[8] or ""),
        "name": str(row[9] or ""),
    }


def get_recent_events(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    events_db = _current_gate_events_db_path()
    if not events_db.exists():
        return []

    _, systemdb_path = _resolve_gate_paths()
    temp_dir = Path(tempfile.mkdtemp(prefix="gate-events-ro-"))
    temp_events = temp_dir / events_db.name
    temp_systemdb = temp_dir / "Gate.mdw"
    try:
        shutil.copy2(events_db, temp_events)
        shutil.copy2(systemdb_path, temp_systemdb)
        conn = pyodbc.connect(_build_connection_string(temp_events, temp_systemdb))
        cursor = conn.cursor()
        try:
            rows = cursor.execute(
                f"""
                SELECT TOP {safe_limit}
                    [Index],
                    [DateTime],
                    EventType,
                    EventCode,
                    DevPtr,
                    RdrPtr,
                    OperatorID,
                    Unit,
                    Message,
                    [Name],
                    UserPtr
                FROM Events
                ORDER BY [Index] DESC
                """
            ).fetchall()
        finally:
            cursor.close()
            conn.close()
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    event_user_ptrs = [int(row[10]) for row in rows if row[10] is not None]
    user_identities = _load_gate_user_event_identities(event_user_ptrs)
    events: list[dict[str, Any]] = []
    for row in rows:
        event_time = row[1]
        user_ptr = int(row[10]) if row[10] is not None else None
        gate_identity = user_identities.get(user_ptr or 0, {})
        events.append(
            {
                "index": int(row[0]),
                "time": event_time.isoformat() if isinstance(event_time, datetime) else str(event_time),
                "event_type": int(row[2]),
                "event_code": int(row[3]),
                "device_id": int(row[4]),
                "access_point_id": int(row[5]),
                "operator_id": int(row[6]),
                "unit": str(row[7] or ""),
                "message": str(row[8] or ""),
                "name": str(row[9] or ""),
                "user_ptr": user_ptr,
                "full_name": gate_identity.get("full_name"),
                "key_type": gate_identity.get("key_type"),
                "key_value": gate_identity.get("key_value"),
            }
        )

    inferred_identities = _infer_anonymous_gate_event_identities(events)
    for event in events:
        event_index = _event_int_value(event, "index")
        if event_index is None:
            continue
        inferred_identity = inferred_identities.get(event_index)
        if inferred_identity is None:
            continue
        event["inferred_full_name"] = inferred_identity.get("full_name")
        event["inferred_key_type"] = inferred_identity.get("key_type")
        event["inferred_key_value"] = inferred_identity.get("key_value")
        event["inferred_user_ptr"] = inferred_identity.get("user_ptr")
        event["identity_source"] = str(inferred_identity.get("source") or "last_used")
    return events


def _sample_phone_user_defaults(cursor: pyodbc.Cursor, *, exclude_user_ptr: int | None = None) -> Any | None:
    phone_key_type_value = _sample_key_type(cursor, "Phone")
    rows = cursor.execute(
        """
        SELECT TOP 1000
            u.UserPtr,
            u.GroupPtr,
            u.IdleNotLimited,
            u.NoFacility,
            u.BgPtr,
            u.SendSms,
            u.SendMail,
            u.UniPassMode,
            u.Phone,
            u.Number,
            u.NumberU,
            u.KeyType,
            u.Deleted,
            u.Status,
            COUNT(a.RdrPtr) AS GsmAccessCount
        FROM (Users AS u
            INNER JOIN AccessTable AS a ON a.UserPtr = u.UserPtr)
            INNER JOIN Readers AS r ON r.RdrPtr = a.RdrPtr
        WHERE r.Name IS NOT NULL
          AND (r.Name LIKE '%GSM%' OR r.Name LIKE '%Р“РЎРњ%' OR r.Name LIKE '%РіСЃРј%')
        GROUP BY
            u.UserPtr,
            u.GroupPtr,
            u.IdleNotLimited,
            u.NoFacility,
            u.BgPtr,
            u.SendSms,
            u.SendMail,
            u.UniPassMode,
            u.Phone,
            u.Number,
            u.NumberU,
            u.KeyType,
            u.Deleted,
            u.Status
        ORDER BY u.UserPtr DESC
        """
    ).fetchall()
    candidates = [
        item
        for item in rows
        if (exclude_user_ptr is None or int(getattr(item, "UserPtr", 0) or 0) != int(exclude_user_ptr))
        and _is_phone_identity_row(item, phone_key_type_value=phone_key_type_value)
        and _is_active_user_status(getattr(item, "Status", None))
        and int(getattr(item, "GsmAccessCount", 0) or 0) > 0
    ]
    if not candidates:
        rows = cursor.execute(
            """
            SELECT TOP 100
                UserPtr,
                GroupPtr,
                IdleNotLimited,
                NoFacility,
                BgPtr,
                SendSms,
                SendMail,
                UniPassMode,
                Phone,
                Number,
                NumberU,
                KeyType,
                Deleted,
                Status
            FROM Users
            ORDER BY UserPtr DESC
            """
        ).fetchall()
        return next(
            (
                item
                for item in rows
                if (exclude_user_ptr is None or int(getattr(item, "UserPtr", 0) or 0) != int(exclude_user_ptr))
                and _is_phone_identity_row(item, phone_key_type_value=phone_key_type_value)
                and _is_active_user_status(getattr(item, "Status", None))
            ),
            None,
        )

    group_counts = Counter(getattr(item, "GroupPtr", None) for item in candidates)
    dominant_group = group_counts.most_common(1)[0][0]
    for item in candidates:
        if getattr(item, "GroupPtr", None) == dominant_group:
            return item
    return candidates[0]


def _sample_vehicle_user_defaults(cursor: pyodbc.Cursor, *, exclude_user_ptr: int | None = None) -> Any | None:
    vehicle_key_type_value = _sample_key_type(cursor, "VehicleNumber")
    rows = cursor.execute(
        """
        SELECT TOP 1000
            u.UserPtr,
            u.GroupPtr,
            u.IdleNotLimited,
            u.NoFacility,
            u.BgPtr,
            u.SendSms,
            u.SendMail,
            u.UniPassMode,
            u.Number,
            u.NumberU,
            u.Phone,
            u.KeyType,
            u.Deleted,
            u.Status,
            COUNT(a.RdrPtr) AS AccessCount
        FROM Users AS u
        LEFT JOIN AccessTable AS a ON a.UserPtr = u.UserPtr
        WHERE u.Number IS NOT NULL
          AND Trim(u.Number) <> ''
        GROUP BY
            u.UserPtr,
            u.GroupPtr,
            u.IdleNotLimited,
            u.NoFacility,
            u.BgPtr,
            u.SendSms,
            u.SendMail,
            u.UniPassMode,
            u.Number,
            u.NumberU,
            u.Phone,
            u.KeyType,
            u.Deleted,
            u.Status
        ORDER BY u.UserPtr DESC
        """
    ).fetchall()

    active_candidates = [
        item
        for item in rows
        if (exclude_user_ptr is None or int(getattr(item, "UserPtr", 0) or 0) != int(exclude_user_ptr))
        and not bool(getattr(item, "Deleted", False))
        and _is_active_user_status(getattr(item, "Status", None))
        and (
            vehicle_key_type_value is None
            or getattr(item, "KeyType", None) == vehicle_key_type_value
        )
    ]
    if not active_candidates:
        return None

    grouped_candidates = [
        item for item in active_candidates if int(getattr(item, "GroupPtr", 0) or 0) > 0
    ]
    if not grouped_candidates:
        grouped_candidates = active_candidates

    group_counts = Counter(getattr(item, "GroupPtr", None) for item in grouped_candidates)
    dominant_group = group_counts.most_common(1)[0][0]
    for item in grouped_candidates:
        if getattr(item, "GroupPtr", None) == dominant_group:
            return item
    return grouped_candidates[0]


def _is_active_user_status(raw_status: Any) -> bool:
    try:
        status_value = None if raw_status is None else int(raw_status)
    except (TypeError, ValueError):
        status_value = raw_status
    return status_value is None or status_value == ACTIVE_USER_STATUS


def _wait_for_gate_open_event(access_point_id: int, previous_index: int | None, timeout_seconds: float) -> dict[str, Any] | None:
    deadline = time_module.monotonic() + timeout_seconds
    while time_module.monotonic() <= deadline:
        event = _latest_gate_open_event(access_point_id)
        if event is not None and (previous_index is None or event["index"] > previous_index):
            return event
        time_module.sleep(0.25)
    return None


def _find_gateterm_access_window(app: Any) -> Any | None:
    for window in app.windows():
        try:
            if _GATETERM_ACCESS_WINDOW_TITLE in str(window.window_text()):
                return app.window(handle=window.handle)
        except Exception:
            continue
    return None


def _open_gateterm_access_window(app: Any) -> Any | None:
    window = _find_gateterm_access_window(app)
    if window is not None:
        return window

    for candidate in app.windows():
        try:
            if "GATE Terminal" not in str(candidate.window_text()):
                continue
            candidate.set_focus()
            candidate.menu_select("Управление->Точки доступа")
            time_module.sleep(0.75)
            return _find_gateterm_access_window(app)
        except Exception:
            continue
    return None


def _open_access_point_via_gateterm_ui(cursor: pyodbc.Cursor, access_point_id: int, external_key_id: str | None = None) -> GateOpenResponse:
    visible_rows = _gateterm_ui_visible_rows(cursor)
    row_map = {int(item["access_point_id"]): index for index, item in enumerate(visible_rows)}
    row_map.update(_gateterm_ui_row_override())

    if access_point_id not in row_map:
        return GateOpenResponse(
            success=False,
            error_code="gateterm_ui_row_not_visible",
            message="GateTerm access-point window does not expose this reader for UI opening",
            details={
                "transport": "gateterm_ui",
                "external_key_id": external_key_id,
                "visible_access_point_ids": [int(item["access_point_id"]) for item in visible_rows],
                "visible_rows": visible_rows,
            },
        )

    try:
        from pywinauto import Application
    except ImportError as exc:
        return GateOpenResponse(
            success=False,
            error_code="gateterm_ui_dependency_missing",
            message=f"pywinauto is required for GateTerm UI transport: {exc}",
            details={"transport": "gateterm_ui", "external_key_id": external_key_id},
        )

    gate_term_exe = _env("GATE_GATETERM_EXE", default=r"C:\GATE\Terminal\GateTerm.exe")
    if not gate_term_exe:
        return GateOpenResponse(
            success=False,
            error_code="gateterm_ui_not_configured",
            message="GATE_GATETERM_EXE is not configured",
            details={"transport": "gateterm_ui", "external_key_id": external_key_id},
        )

    previous_event = _latest_gate_open_event(access_point_id)
    previous_index = int(previous_event["index"]) if previous_event is not None else None

    app: Any | None = None
    try:
        app = Application(backend="win32").connect(path=gate_term_exe)
        window = _open_gateterm_access_window(app)
        if window is None:
            raise RuntimeError("GateTerm access-point window is not open and could not be opened from the menu")

        window.set_focus()
        grid = window.child_window(class_name="MSFlexGridWndClass")
        button = window.child_window(control_id=11, class_name="ThunderRT6CommandButton")
        rect = grid.rectangle()

        row_index = int(row_map[access_point_id])
        row_height = _env_int("GATE_GATETERM_UI_ROW_HEIGHT", 16)
        header_height = _env_int("GATE_GATETERM_UI_HEADER_HEIGHT", 17)
        x_offset = _env_int("GATE_GATETERM_UI_X_OFFSET", 70)
        y_offset = header_height + (row_height * row_index) + max(row_height // 2, 1)
        if y_offset <= 0 or rect.top + y_offset >= rect.bottom:
            raise RuntimeError(f"Computed GateTerm row coordinate is outside the grid: row_index={row_index}")

        grid.click_input(coords=(x_offset, y_offset))
        button.click_input()

        timeout_seconds = _env_float("GATE_GATETERM_UI_VERIFY_TIMEOUT_SECONDS", 6.0)
        observed_event = _wait_for_gate_open_event(access_point_id, previous_index, timeout_seconds)
        details = {
            "transport": "gateterm_ui",
            "external_key_id": external_key_id,
            "access_point_id": access_point_id,
            "row_index": row_index,
            "visible_rows": visible_rows,
            "previous_event": previous_event,
            "observed_event": observed_event,
        }
        if observed_event is None:
            return GateOpenResponse(
                success=False,
                error_code="gateterm_ui_event_not_observed",
                message="GateTerm UI command was sent, but no matching Gate operator event was observed",
                details=details,
            )

        return GateOpenResponse(
            success=True,
            message=f"Access point {access_point_id} opened via GateTerm UI",
            details=details,
        )
    except Exception as exc:
        return GateOpenResponse(
            success=False,
            error_code="gateterm_ui_error",
            message=f"GateTerm UI open failed: {exc}",
            details={
                "transport": "gateterm_ui",
                "external_key_id": external_key_id,
                "access_point_id": access_point_id,
                "row_index": row_map.get(access_point_id),
                "visible_rows": visible_rows,
            },
        )
    finally:
        if app is not None:
            try:
                _close_gateterm_access_window_if_open(app)
            except Exception:
                pass


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

        if _configured_open_transport() in _GATETERM_UI_TRANSPORTS:
            transport_result = _open_access_point_via_gateterm_ui(
                cursor,
                access_point_id=access_point_id,
                external_key_id=external_key_id,
            )
            return {
                "success": transport_result.success,
                "error_code": transport_result.error_code,
                "message": transport_result.message,
                "details": transport_result.details,
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
