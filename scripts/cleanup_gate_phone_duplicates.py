from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _normalize_phone_candidate(value: Any, gate_runtime: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    try:
        return gate_runtime._normalize_phone(digits)
    except Exception:
        return ""


def _load_access_ids(cursor: Any, user_ptr: int) -> list[int]:
    rows = cursor.execute(
        """
        SELECT RdrPtr
        FROM AccessTable
        WHERE UserPtr = ?
        ORDER BY RdrPtr
        """,
        (user_ptr,),
    ).fetchall()
    result: list[int] = []
    for row in rows:
        raw_reader_ptr = getattr(row, "RdrPtr", None)
        if raw_reader_ptr is None:
            raw_reader_ptr = row[0]
        result.append(int(raw_reader_ptr))
    return result


def _resolve_gsm_access_point_ids(cursor: Any, gate_runtime: Any, explicit_ids: list[int]) -> list[int]:
    if explicit_ids:
        seen: set[int] = set()
        resolved: list[int] = []
        for point_id in explicit_ids:
            if point_id in seen:
                continue
            seen.add(point_id)
            resolved.append(point_id)
        return resolved

    rows = cursor.execute(
        """
        SELECT RdrPtr, Name
        FROM Readers
        ORDER BY RdrPtr
        """
    ).fetchall()
    resolved = []
    seen: set[int] = set()
    for row in rows:
        point_id = int(getattr(row, "RdrPtr"))
        if point_id in seen:
            continue
        if gate_runtime._looks_like_phone_reader(getattr(row, "Name", None)):
            seen.add(point_id)
            resolved.append(point_id)
    return resolved


def _collect_gate_rows(
    cursor: Any,
    gate_runtime: Any,
    normalized_phone: str,
    gsm_ids: list[int],
) -> tuple[Any | None, str, list[dict[str, Any]]]:
    phone_key_type_value = gate_runtime._sample_key_type(cursor, "Phone", gsm_ids)
    expected_phone = gate_runtime._format_phone_for_storage(cursor, normalized_phone)
    rows = cursor.execute(
        """
        SELECT
            UserPtr,
            KeyType,
            Number,
            NumberU,
            Phone,
            LastName,
            FirstName,
            FatherName,
            Deleted,
            UseExpiry,
            ExpiryDate,
            ExpiryTime,
            Status,
            LockDate
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()

    result: list[dict[str, Any]] = []
    gsm_set = set(int(point_id) for point_id in gsm_ids)
    for row in rows:
        user_ptr = int(getattr(row, "UserPtr", 0) or 0)
        if user_ptr <= 0:
            continue

        phone_match = gate_runtime._normalize_optional_phone(getattr(row, "Phone", None)) == normalized_phone
        number_match = _normalize_phone_candidate(getattr(row, "Number", None), gate_runtime) == normalized_phone
        number_u_match = _normalize_phone_candidate(getattr(row, "NumberU", None), gate_runtime) == normalized_phone
        if not (phone_match or number_match or number_u_match):
            continue

        access_ids = _load_access_ids(cursor, user_ptr)
        gsm_access_ids = [point_id for point_id in access_ids if point_id in gsm_set]
        expiry = gate_runtime._combine_expiry(getattr(row, "ExpiryDate", None), getattr(row, "ExpiryTime", None))
        result.append(
            {
                "row": row,
                "user_ptr": user_ptr,
                "phone_match": phone_match,
                "number_match": number_match,
                "number_u_match": number_u_match,
                "access_ids": access_ids,
                "gsm_access_ids": gsm_access_ids,
                "looks_like_phone_identity": gate_runtime._is_phone_identity_row(
                    row,
                    phone_key_type_value=phone_key_type_value,
                ),
                "expiry": expiry,
            }
        )

    return phone_key_type_value, expected_phone, result


def _candidate_score(
    item: dict[str, Any],
    *,
    expected_phone: str,
    gsm_ids: list[int],
    phone_key_type_value: Any | None,
) -> tuple[int, int]:
    row = item["row"]
    gsm_set = set(gsm_ids)
    score = 0
    if not bool(getattr(row, "Deleted", False)):
        score += 1000
    if item["looks_like_phone_identity"]:
        score += 300
    if phone_key_type_value is not None and getattr(row, "KeyType", None) == phone_key_type_value:
        score += 100
    if item["number_match"]:
        score += 60
    if item["number_u_match"]:
        score += 60
    if str(getattr(row, "Phone", "") or "") == expected_phone:
        score += 40
    if sorted(item["gsm_access_ids"]) == sorted(gsm_ids):
        score += 25
    score -= 10 * len([point_id for point_id in item["access_ids"] if point_id not in gsm_set])
    if bool(getattr(row, "UseExpiry", False)):
        expiry = item["expiry"]
        if expiry is None:
            score -= 50
        else:
            expiry_utc = expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry.astimezone(timezone.utc)
            if expiry_utc <= datetime.now(timezone.utc):
                score -= 100
    return score, item["user_ptr"]


def _pick_keep_user_ptr(
    items: list[dict[str, Any]],
    *,
    expected_phone: str,
    gsm_ids: list[int],
    phone_key_type_value: Any | None,
) -> int | None:
    active_items = [item for item in items if not bool(getattr(item["row"], "Deleted", False))]
    if not active_items:
        return None
    best = max(
        active_items,
        key=lambda item: _candidate_score(
            item,
            expected_phone=expected_phone,
            gsm_ids=gsm_ids,
            phone_key_type_value=phone_key_type_value,
        ),
    )
    return int(best["user_ptr"])


def _plan_gate_action(
    item: dict[str, Any],
    *,
    keep_user_ptr: int | None,
    clear_contact_phone: bool,
    purge_all: bool,
) -> str | None:
    row = item["row"]
    if purge_all:
        if item["phone_match"] or item["number_match"] or item["number_u_match"]:
            return "purge_gate_user"
        return None

    if bool(getattr(row, "Deleted", False)):
        return None
    if keep_user_ptr is not None and item["user_ptr"] == keep_user_ptr:
        return "keep"
    if item["looks_like_phone_identity"] or item["gsm_access_ids"] or item["number_match"] or item["number_u_match"]:
        return "deactivate"
    if clear_contact_phone and item["phone_match"]:
        return "clear_phone"
    return None


def _apply_gate_action(cursor: Any, action: str, user_ptr: int) -> None:
    if action == "deactivate":
        action = "purge_gate_user"

    if action == "purge_gate_user":
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
                [NumberU] = ?,
                [LastName] = ?,
                [FirstName] = ?,
                [FatherName] = ?,
                [Status] = ?
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
                None,
                None,
                None,
                0,
                user_ptr,
            ),
        )
        return

    if action == "clear_phone":
        cursor.execute("UPDATE Users SET Phone = ? WHERE UserPtr = ?", (None, user_ptr))
        return

    if action == "keep":
        return

    raise ValueError(f"Unsupported Gate cleanup action: {action}")


def _resolve_backend_db_path(project_root: Path) -> Path | None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return None

    prefixes = (
        "sqlite+aiosqlite:///",
        "sqlite:///",
    )
    raw_path: str | None = None
    for prefix in prefixes:
        if database_url.startswith(prefix):
            raw_path = database_url[len(prefix) :]
            break
    if raw_path is None:
        return None

    path = Path(raw_path)
    if not path.is_absolute():
        path = (project_root / path).resolve()
    return path


def _collect_backend_requests(db_path: Path, normalized_phone: str, gate_runtime: Any) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT
                id,
                resident_id,
                key_type,
                key_value,
                gate_key_id,
                contact_phone,
                status,
                created_at,
                cancelled_at
            FROM requests
            ORDER BY id DESC
            """
        ).fetchall()
    finally:
        connection.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        key_type = str(row["key_type"] or "")
        key_value_match = key_type == "Phone" and _normalize_phone_candidate(row["key_value"], gate_runtime) == normalized_phone
        contact_phone_match = _normalize_phone_candidate(row["contact_phone"], gate_runtime) == normalized_phone
        if not (key_value_match or contact_phone_match):
            continue
        result.append(
            {
                "id": int(row["id"]),
                "resident_id": int(row["resident_id"]),
                "key_type": key_type,
                "key_value": row["key_value"],
                "gate_key_id": row["gate_key_id"],
                "contact_phone": row["contact_phone"],
                "status": row["status"],
                "created_at": row["created_at"],
                "cancelled_at": row["cancelled_at"],
            }
        )
    return result


def _apply_backend_request_purge(db_path: Path, request_ids: list[int]) -> int:
    if not request_ids:
        return 0
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.cursor()
        cursor.executemany("DELETE FROM requests WHERE id = ?", [(request_id,) for request_id in request_ids])
        deleted = int(cursor.rowcount or 0)
        connection.commit()
        return deleted
    finally:
        connection.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or clean Gate phone/GSM users for the specified numbers. "
            "Default mode de-duplicates GSM identities; --purge-all removes every matching Gate row "
            "and matching backend request."
        )
    )
    parser.add_argument("phones", nargs="+", help="Phone numbers to inspect and clean up.")
    parser.add_argument("--mdb", default=os.environ.get("GATE_MDB_PATH"))
    parser.add_argument("--systemdb", default=os.environ.get("GATE_SYSTEMDB_PATH") or os.environ.get("GATE_MDW_PATH"))
    parser.add_argument("--uid", default=os.environ.get("GATE_MDB_UID") or os.environ.get("GATE_UID"))
    parser.add_argument(
        "--pwd",
        default=os.environ.get("GATE_MDB_PWD") if os.environ.get("GATE_MDB_PWD") is not None else os.environ.get("GATE_PWD"),
    )
    parser.add_argument("--driver", default=os.environ.get("GATE_ODBC_DRIVER") or "Microsoft Access Driver (*.mdb, *.accdb)")
    parser.add_argument(
        "--gsm-access-point-id",
        dest="gsm_access_point_ids",
        action="append",
        type=int,
        default=[],
        help="Explicit GSM reader id. Repeat the flag to pass multiple reader ids.",
    )
    parser.add_argument(
        "--clear-contact-phone",
        action="store_true",
        help="In dedupe mode, also clear Phone on non-phone rows that still carry the same contact number.",
    )
    parser.add_argument(
        "--purge-all",
        action="store_true",
        help="Purge all Gate users and backend requests related to the specified phone numbers.",
    )
    parser.add_argument("--apply", action="store_true", help="Write cleanup changes into the MDB and backend DB. Default is dry-run.")
    return parser.parse_args()


def _configure_env(args: argparse.Namespace) -> tuple[Path, Path]:
    if not args.mdb:
        raise SystemExit("Pass --mdb or set GATE_MDB_PATH.")
    if not args.systemdb:
        raise SystemExit("Pass --systemdb or set GATE_SYSTEMDB_PATH.")
    if not args.uid:
        raise SystemExit("Pass --uid or set GATE_MDB_UID.")
    if args.pwd is None:
        raise SystemExit("Pass --pwd or set GATE_MDB_PWD (use an empty string if the password is empty).")

    mdb_path = Path(args.mdb).expanduser().resolve()
    systemdb_path = Path(args.systemdb).expanduser().resolve()
    if not mdb_path.exists():
        raise SystemExit(f"MDB file not found: {mdb_path}")
    if not systemdb_path.exists():
        raise SystemExit(f"SystemDB file not found: {systemdb_path}")

    os.environ["GATE_MDB_PATH"] = str(mdb_path)
    os.environ["GATE_SYSTEMDB_PATH"] = str(systemdb_path)
    os.environ["GATE_MDB_UID"] = args.uid
    os.environ["GATE_MDB_PWD"] = args.pwd
    os.environ["GATE_ODBC_DRIVER"] = args.driver
    return mdb_path, systemdb_path


def main() -> int:
    args = _parse_args()
    mdb_path, systemdb_path = _configure_env(args)

    from backend.app.scripts import gate_runtime

    backend_db_path = _resolve_backend_db_path(PROJECT_ROOT)
    gate_plans: list[dict[str, Any]] = []
    backend_plans: list[dict[str, Any]] = []

    with gate_runtime._readonly_cursor() as (_conn, cursor):
        gsm_ids = _resolve_gsm_access_point_ids(cursor, gate_runtime, args.gsm_access_point_ids)
        if not gsm_ids:
            raise SystemExit("No GSM access points were resolved. Pass --gsm-access-point-id explicitly.")

        for raw_phone in args.phones:
            normalized_phone = gate_runtime._normalize_phone(raw_phone)
            phone_key_type_value, expected_phone, items = _collect_gate_rows(cursor, gate_runtime, normalized_phone, gsm_ids)
            keep_user_ptr = None
            if not args.purge_all:
                keep_user_ptr = _pick_keep_user_ptr(
                    items,
                    expected_phone=expected_phone,
                    gsm_ids=gsm_ids,
                    phone_key_type_value=phone_key_type_value,
                )
            planned_gate_rows = [
                {
                    **item,
                    "action": _plan_gate_action(
                        item,
                        keep_user_ptr=keep_user_ptr,
                        clear_contact_phone=args.clear_contact_phone or args.purge_all,
                        purge_all=args.purge_all,
                    ),
                }
                for item in items
            ]
            gate_plans.append(
                {
                    "raw_phone": raw_phone,
                    "normalized_phone": normalized_phone,
                    "phone_key_type_value": phone_key_type_value,
                    "expected_phone": expected_phone,
                    "keep_user_ptr": keep_user_ptr,
                    "items": planned_gate_rows,
                }
            )
            backend_plans.append(
                {
                    "raw_phone": raw_phone,
                    "normalized_phone": normalized_phone,
                    "items": _collect_backend_requests(backend_db_path, normalized_phone, gate_runtime)
                    if backend_db_path is not None
                    else [],
                }
            )

    print(f"MDB: {mdb_path}")
    print(f"SystemDB: {systemdb_path}")
    print(f"GSM reader ids: {gsm_ids}")
    print(f"Mode: {'purge-all' if args.purge_all else 'dedupe'}")
    print(f"Backend DB: {backend_db_path if backend_db_path is not None else '(not sqlite / not resolved)'}")
    print()

    gate_actions = 0
    backend_actions = 0

    for gate_plan, backend_plan in zip(gate_plans, backend_plans):
        print(f"Phone: {gate_plan['raw_phone']} -> {gate_plan['normalized_phone']}")
        print(f"Expected storage Phone: {gate_plan['expected_phone']!r}")
        print(f"Keep UserPtr: {gate_plan['keep_user_ptr']}")

        if not gate_plan["items"]:
            print("  Gate users: no matching rows")
        else:
            for item in gate_plan["items"]:
                row = item["row"]
                action = item["action"] or "skip"
                print(
                    "  "
                    f"Gate UserPtr={item['user_ptr']} action={action} "
                    f"Deleted={bool(getattr(row, 'Deleted', False))} "
                    f"KeyType={getattr(row, 'KeyType', None)!r} "
                    f"Number={getattr(row, 'Number', None)!r} "
                    f"NumberU={getattr(row, 'NumberU', None)!r} "
                    f"Phone={getattr(row, 'Phone', None)!r} "
                    f"Access={item['access_ids']}"
                )
                if action in {"deactivate", "clear_phone", "purge_gate_user"}:
                    gate_actions += 1

        if not backend_plan["items"]:
            print("  Backend requests: no matching rows")
        else:
            for item in backend_plan["items"]:
                request_action = "delete_request" if args.purge_all else "report_only"
                print(
                    "  "
                    f"Backend Request id={item['id']} action={request_action} "
                    f"key_type={item['key_type']!r} key_value={item['key_value']!r} "
                    f"contact_phone={item['contact_phone']!r} status={item['status']!r} "
                    f"gate_key_id={item['gate_key_id']!r}"
                )
                if args.purge_all:
                    backend_actions += 1
        print()

    if not args.apply:
        print("Dry-run only. Re-run with --apply to write cleanup changes.")
        return 0

    if gate_actions == 0 and backend_actions == 0:
        print("Nothing to change.")
        return 0

    with gate_runtime._transaction_cursor() as (_conn, cursor):
        for plan in gate_plans:
            normalized_phone = plan["normalized_phone"]
            _phone_key_type_value, expected_phone, items = _collect_gate_rows(cursor, gate_runtime, normalized_phone, gsm_ids)
            keep_user_ptr = None
            if not args.purge_all:
                keep_user_ptr = _pick_keep_user_ptr(
                    items,
                    expected_phone=expected_phone,
                    gsm_ids=gsm_ids,
                    phone_key_type_value=plan["phone_key_type_value"],
                )
            for item in items:
                action = _plan_gate_action(
                    item,
                    keep_user_ptr=keep_user_ptr,
                    clear_contact_phone=args.clear_contact_phone or args.purge_all,
                    purge_all=args.purge_all,
                )
                if action in {"deactivate", "clear_phone", "purge_gate_user"}:
                    _apply_gate_action(cursor, action, int(item["user_ptr"]))

    if args.purge_all and backend_db_path is not None and backend_db_path.exists():
        deleted_requests = 0
        for plan in backend_plans:
            deleted_requests += _apply_backend_request_purge(
                backend_db_path,
                [int(item["id"]) for item in plan["items"]],
            )
        print(f"Backend requests deleted: {deleted_requests}")

    print("Cleanup applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
