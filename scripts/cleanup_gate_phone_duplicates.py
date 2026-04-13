from __future__ import annotations

import argparse
import os
import sys
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
    return [int(getattr(row, "RdrPtr", row[0])) for row in rows]


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


def _collect_phone_rows(cursor: Any, gate_runtime: Any, normalized_phone: str, gsm_ids: list[int]) -> tuple[Any | None, str, list[dict[str, Any]]]:
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
            Deleted,
            UseExpiry,
            ExpiryDate,
            ExpiryTime
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


def _candidate_score(item: dict[str, Any], *, normalized_phone: str, expected_phone: str, gsm_ids: list[int], phone_key_type_value: Any | None) -> tuple[int, int]:
    row = item["row"]
    score = 0
    if not bool(getattr(row, "Deleted", False)):
        score += 1000
    if item["looks_like_phone_identity"]:
        score += 300
    if phone_key_type_value is not None and getattr(row, "KeyType", None) == phone_key_type_value:
        score += 100
    if str(getattr(row, "Number", "") or "") == normalized_phone:
        score += 50
    if str(getattr(row, "NumberU", "") or "") == normalized_phone:
        score += 50
    if str(getattr(row, "Phone", "") or "") == expected_phone:
        score += 25
    if sorted(item["gsm_access_ids"]) == sorted(gsm_ids):
        score += 25
    score -= 10 * len([point_id for point_id in item["access_ids"] if point_id not in set(gsm_ids)])
    if bool(getattr(row, "UseExpiry", False)):
        expiry = item["expiry"]
        if expiry is None:
            score -= 50
        else:
            expiry_utc = expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry.astimezone(timezone.utc)
            if expiry_utc <= datetime.now(timezone.utc):
                score -= 100
    return score, item["user_ptr"]


def _pick_keep_user_ptr(items: list[dict[str, Any]], *, normalized_phone: str, expected_phone: str, gsm_ids: list[int], phone_key_type_value: Any | None) -> int | None:
    active_items = [item for item in items if not bool(getattr(item["row"], "Deleted", False))]
    if not active_items:
        return None
    best = max(
        active_items,
        key=lambda item: _candidate_score(
            item,
            normalized_phone=normalized_phone,
            expected_phone=expected_phone,
            gsm_ids=gsm_ids,
            phone_key_type_value=phone_key_type_value,
        ),
    )
    return int(best["user_ptr"])


def _plan_action(item: dict[str, Any], *, keep_user_ptr: int | None, clear_contact_phone: bool) -> str | None:
    row = item["row"]
    if bool(getattr(row, "Deleted", False)):
        return None
    if keep_user_ptr is not None and item["user_ptr"] == keep_user_ptr:
        return "keep"
    if item["looks_like_phone_identity"] or item["gsm_access_ids"] or item["number_match"] or item["number_u_match"]:
        return "deactivate"
    if clear_contact_phone and item["phone_match"]:
        return "clear_phone"
    return None


def _apply_action(cursor: Any, action: str, user_ptr: int) -> None:
    if action == "deactivate":
        cursor.execute("DELETE FROM AccessTable WHERE UserPtr = ?", (user_ptr,))
        cursor.execute(
            """
            UPDATE Users
            SET Deleted = ?, UseExpiry = ?, ExpiryDate = ?, ExpiryTime = ?, LockDate = ?
            WHERE UserPtr = ?
            """,
            (True, False, None, None, None, user_ptr),
        )
        return
    if action == "clear_phone":
        cursor.execute("UPDATE Users SET Phone = ? WHERE UserPtr = ?", (None, user_ptr))
        return
    if action == "keep":
        return
    raise ValueError(f"Unsupported cleanup action: {action}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deactivate duplicate Gate GSM/phone users for the specified phone numbers."
    )
    parser.add_argument("phones", nargs="+", help="Phone numbers to inspect and clean up.")
    parser.add_argument("--mdb", default=os.environ.get("GATE_MDB_PATH"))
    parser.add_argument("--systemdb", default=os.environ.get("GATE_SYSTEMDB_PATH") or os.environ.get("GATE_MDW_PATH"))
    parser.add_argument("--uid", default=os.environ.get("GATE_MDB_UID") or os.environ.get("GATE_UID"))
    parser.add_argument("--pwd", default=os.environ.get("GATE_MDB_PWD") if os.environ.get("GATE_MDB_PWD") is not None else os.environ.get("GATE_PWD"))
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
        help="Also clear Phone on non-phone rows that still carry the same contact number.",
    )
    parser.add_argument("--apply", action="store_true", help="Write cleanup changes into the MDB. Default is dry-run.")
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

    with gate_runtime._readonly_cursor() as (_conn, cursor):
        gsm_ids = _resolve_gsm_access_point_ids(cursor, gate_runtime, args.gsm_access_point_ids)
        if not gsm_ids:
            raise SystemExit("No GSM access points were resolved. Pass --gsm-access-point-id explicitly.")

        phone_plans: list[dict[str, Any]] = []
        for raw_phone in args.phones:
            normalized_phone = gate_runtime._normalize_phone(raw_phone)
            phone_key_type_value, expected_phone, items = _collect_phone_rows(cursor, gate_runtime, normalized_phone, gsm_ids)
            keep_user_ptr = _pick_keep_user_ptr(
                items,
                normalized_phone=normalized_phone,
                expected_phone=expected_phone,
                gsm_ids=gsm_ids,
                phone_key_type_value=phone_key_type_value,
            )
            planned = [
                {
                    **item,
                    "action": _plan_action(
                        item,
                        keep_user_ptr=keep_user_ptr,
                        clear_contact_phone=args.clear_contact_phone,
                    ),
                }
                for item in items
            ]
            phone_plans.append(
                {
                    "raw_phone": raw_phone,
                    "normalized_phone": normalized_phone,
                    "phone_key_type_value": phone_key_type_value,
                    "expected_phone": expected_phone,
                    "keep_user_ptr": keep_user_ptr,
                    "items": planned,
                }
            )

    print(f"MDB: {mdb_path}")
    print(f"SystemDB: {systemdb_path}")
    print(f"GSM reader ids: {gsm_ids}")
    print()

    actionable = 0
    for plan in phone_plans:
        print(f"Phone: {plan['raw_phone']} -> {plan['normalized_phone']}")
        print(f"Expected storage Phone: {plan['expected_phone']!r}")
        print(f"Keep UserPtr: {plan['keep_user_ptr']}")
        if not plan["items"]:
            print("  no matching rows")
            print()
            continue

        for item in plan["items"]:
            row = item["row"]
            action = item["action"] or "skip"
            print(
                "  "
                f"UserPtr={item['user_ptr']} action={action} "
                f"Deleted={bool(getattr(row, 'Deleted', False))} "
                f"KeyType={getattr(row, 'KeyType', None)!r} "
                f"Number={getattr(row, 'Number', None)!r} "
                f"NumberU={getattr(row, 'NumberU', None)!r} "
                f"Phone={getattr(row, 'Phone', None)!r} "
                f"Access={item['access_ids']}"
            )
            if action in {"deactivate", "clear_phone"}:
                actionable += 1
        print()

    if not args.apply:
        print("Dry-run only. Re-run with --apply to write cleanup changes into the MDB.")
        return 0

    if actionable == 0:
        print("Nothing to change.")
        return 0

    with gate_runtime._transaction_cursor() as (_conn, cursor):
        for plan in phone_plans:
            normalized_phone = plan["normalized_phone"]
            _phone_key_type_value, _expected_phone, items = _collect_phone_rows(cursor, gate_runtime, normalized_phone, gsm_ids)
            keep_user_ptr = _pick_keep_user_ptr(
                items,
                normalized_phone=normalized_phone,
                expected_phone=plan["expected_phone"],
                gsm_ids=gsm_ids,
                phone_key_type_value=plan["phone_key_type_value"],
            )
            for item in items:
                action = _plan_action(
                    item,
                    keep_user_ptr=keep_user_ptr,
                    clear_contact_phone=args.clear_contact_phone,
                )
                if action in {"deactivate", "clear_phone"}:
                    _apply_action(cursor, action, int(item["user_ptr"]))

    print("Cleanup applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
