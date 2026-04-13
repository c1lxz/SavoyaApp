from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_gsm_access_point_ids(cursor: Any, gate_runtime: Any, explicit_ids: list[int]) -> list[int]:
    if explicit_ids:
        resolved: list[int] = []
        seen: set[int] = set()
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


def _collect_matching_rows(cursor: Any, gate_runtime: Any, normalized_phone: str, gsm_ids: list[int]) -> list[dict[str, Any]]:
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
            ExpiryTime
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()

    phone_key_type_value = gate_runtime._sample_key_type(cursor, "Phone", gsm_ids)
    result: list[dict[str, Any]] = []
    for row in rows:
        user_ptr = int(getattr(row, "UserPtr", 0) or 0)
        if user_ptr <= 0:
            continue

        phone_match = gate_runtime._normalize_optional_phone(getattr(row, "Phone", None)) == normalized_phone
        number_match = gate_runtime._normalize_optional_phone(getattr(row, "Number", None)) == normalized_phone
        number_u_match = gate_runtime._normalize_optional_phone(getattr(row, "NumberU", None)) == normalized_phone
        if not (phone_match or number_match or number_u_match):
            continue

        access_rows = cursor.execute(
            """
            SELECT RdrPtr
            FROM AccessTable
            WHERE UserPtr = ?
            ORDER BY RdrPtr
            """,
            (user_ptr,),
        ).fetchall()
        access_ids = [int(getattr(item, "RdrPtr")) for item in access_rows]
        gsm_access_ids = [point_id for point_id in access_ids if point_id in gsm_ids]
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
            }
        )
    return result


def _purge_matching_rows(
    cursor: Any,
    gate_runtime: Any,
    *,
    normalized_phone: str,
    gsm_ids: list[int],
    clear_contact_phone: bool,
) -> list[int]:
    removed: list[int] = []
    items = _collect_matching_rows(cursor, gate_runtime, normalized_phone, gsm_ids)
    for item in items:
        row = item["row"]
        user_ptr = int(item["user_ptr"])
        if bool(getattr(row, "Deleted", False)):
            continue
        if item["looks_like_phone_identity"] or item["gsm_access_ids"] or item["number_match"] or item["number_u_match"]:
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
            removed.append(user_ptr)
            continue
        if clear_contact_phone and item["phone_match"]:
            cursor.execute("UPDATE Users SET Phone = ? WHERE UserPtr = ?", (None, user_ptr))
    return removed


def _print_state(cursor: Any, gate_runtime: Any, normalized_phone: str, gsm_ids: list[int]) -> None:
    expected_phone = gate_runtime._format_phone_for_storage(cursor, normalized_phone)
    print(f"Normalized phone: {normalized_phone}")
    print(f"Expected storage Phone: {expected_phone!r}")
    items = _collect_matching_rows(cursor, gate_runtime, normalized_phone, gsm_ids)
    if not items:
        print("Gate users: no matching rows")
        return
    for item in items:
        row = item["row"]
        print(
            f"UserPtr={item['user_ptr']} Deleted={getattr(row, 'Deleted', None)!r} "
            f"KeyType={getattr(row, 'KeyType', None)!r} "
            f"Phone={getattr(row, 'Phone', None)!r} Number={getattr(row, 'Number', None)!r} "
            f"NumberU={getattr(row, 'NumberU', None)!r} "
            f"LastName={getattr(row, 'LastName', None)!r} FirstName={getattr(row, 'FirstName', None)!r} "
            f"UseExpiry={getattr(row, 'UseExpiry', None)!r} Access={item['access_ids']}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or force-rebuild a phone/GSM pass directly in Gate config.mdb. "
            "Use --purge-existing when Gate Terminal appears to hold stale state for the same phone."
        )
    )
    parser.add_argument("phone", help="Phone number to inspect or rebuild.")
    parser.add_argument("--resident-name", default=None, help="Resident full name for the rebuilt Gate user.")
    parser.add_argument("--plot-number", default=None, help="Plot number written to Users.Details1.")
    parser.add_argument("--permanent", action="store_true", help="Create a permanent phone pass.")
    parser.add_argument("--expires-at", default=None, help="ISO datetime for a temporary pass.")
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
        help="Explicit GSM reader id. Repeat for multiple readers.",
    )
    parser.add_argument("--purge-existing", action="store_true", help="Deactivate existing Gate rows for the same phone before rebuild.")
    parser.add_argument(
        "--clear-contact-phone",
        action="store_true",
        help="Also clear Phone on non-phone rows that still carry this number when purging.",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes into the MDB. Default is dry-run.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not args.mdb:
        raise SystemExit("Pass --mdb or set GATE_MDB_PATH.")
    if not args.systemdb:
        raise SystemExit("Pass --systemdb or set GATE_SYSTEMDB_PATH.")
    if not args.uid:
        raise SystemExit("Pass --uid or set GATE_MDB_UID.")
    if args.pwd is None:
        raise SystemExit("Pass --pwd or set GATE_MDB_PWD (use an empty string if the password is empty).")

    if args.apply and not args.resident_name:
        raise SystemExit("Pass --resident-name when using --apply.")
    if args.apply and not args.plot_number:
        raise SystemExit("Pass --plot-number when using --apply.")
    if args.apply and not args.permanent and not args.expires_at:
        raise SystemExit("Pass --permanent or --expires-at when using --apply.")

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

    from backend.app.scripts import gate_runtime

    normalized_phone = gate_runtime._normalize_phone(args.phone)
    expires_at = _parse_expiry(args.expires_at)

    with gate_runtime._readonly_cursor() as (_conn, cursor):
        gsm_ids = _resolve_gsm_access_point_ids(cursor, gate_runtime, args.gsm_access_point_ids)
        if not gsm_ids:
            raise SystemExit("No GSM access points were resolved. Pass --gsm-access-point-id explicitly.")

        print(f"MDB: {mdb_path}")
        print(f"SystemDB: {systemdb_path}")
        print(f"GSM reader ids: {gsm_ids}")
        print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
        print()
        print("Current Gate state")
        _print_state(cursor, gate_runtime, normalized_phone, gsm_ids)

    if not args.apply:
        print()
        print("Dry-run only. Re-run with --apply to rebuild the Gate phone pass.")
        return 0

    removed: list[int] = []
    if args.purge_existing:
        with gate_runtime._transaction_cursor() as (_conn, cursor):
            removed = _purge_matching_rows(
                cursor,
                gate_runtime,
                normalized_phone=normalized_phone,
                gsm_ids=gsm_ids,
                clear_contact_phone=args.clear_contact_phone,
            )

    if args.permanent:
        user_ptr = gate_runtime.add_permanent_key(
            "Phone",
            args.phone,
            args.phone,
            gsm_ids,
            resident_name=args.resident_name,
            plot_number=args.plot_number,
        )
    else:
        if expires_at is None:
            raise SystemExit("--expires-at is required for a temporary pass.")
        user_ptr = gate_runtime.add_temporary_key(
            "Phone",
            args.phone,
            args.phone,
            expires_at,
            gsm_ids,
            resident_name=args.resident_name,
            plot_number=args.plot_number,
        )

    print()
    if removed:
        print(f"Purged UserPtr: {removed}")
    print(f"Rebuilt Gate phone pass as UserPtr={user_ptr}")

    with gate_runtime._readonly_cursor() as (_conn, cursor):
        print()
        print("Gate state after rebuild")
        _print_state(cursor, gate_runtime, normalized_phone, gsm_ids)

    print()
    print("If Gate Terminal still shows the old owner after this rebuild, restart Gate Terminal/Server on the live machine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
