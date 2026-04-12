param(
    [string]$LeftNeedle,
    [string]$RightNeedle,
    [string]$MdbPath = $env:GATE_MDB_PATH,
    [string]$SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH }),
    [string]$Uid = $(if ($env:GATE_MDB_UID) { $env:GATE_MDB_UID } else { $env:GATE_UID }),
    [string]$Pwd = $(if ($null -ne $env:GATE_MDB_PWD) { $env:GATE_MDB_PWD } else { $env:GATE_PWD }),
    [string]$PythonLauncher = $(if ($env:GATE_PYTHON_LAUNCHER) { $env:GATE_PYTHON_LAUNCHER } else { "py" }),
    [string]$PythonVersion = $(if ($env:GATE_PYTHON_VERSION) { $env:GATE_PYTHON_VERSION } else { "-3.12-32" }),
    [string]$Driver = $(if ($env:GATE_ODBC_DRIVER) { $env:GATE_ODBC_DRIVER } else { "Microsoft Access Driver (*.mdb, *.accdb)" }),
    [int]$Top = 5
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"

if (Test-Path -LiteralPath $envFile) {
    Get-Content -LiteralPath $envFile |
        Where-Object { $_ -match '^\s*[^#].*=.*$' } |
        ForEach-Object {
            $name, $value = $_ -split '=', 2
            $name = $name.Trim()
            $value = $value.Trim().Trim('"')
            if (-not (Test-Path "Env:$name")) {
                Set-Item -Path "Env:$name" -Value $value
            }
        }
}

if (-not $LeftNeedle) {
    throw "Pass -LeftNeedle with phone digits, UserPtr, or name fragment."
}

if (-not $MdbPath) {
    $MdbPath = $env:GATE_MDB_PATH
}
if (-not $SystemDbPath) {
    $SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH })
}
if (-not $Uid) {
    $Uid = $(if ($env:GATE_MDB_UID) { $env:GATE_MDB_UID } else { $env:GATE_UID })
}
if (-not $PSBoundParameters.ContainsKey("Pwd")) {
    $Pwd = $(if ($null -ne $env:GATE_MDB_PWD) { $env:GATE_MDB_PWD } else { $env:GATE_PWD })
}

$localMdbFallback = Join-Path $projectRoot "config.mdb"
$localSystemDbFallback = Join-Path $projectRoot "Gate.mdw"
if ((-not $MdbPath -or -not (Test-Path -LiteralPath $MdbPath)) -and (Test-Path -LiteralPath $localMdbFallback)) {
    $MdbPath = $localMdbFallback
}
if ((-not $SystemDbPath -or -not (Test-Path -LiteralPath $SystemDbPath)) -and (Test-Path -LiteralPath $localSystemDbFallback)) {
    $SystemDbPath = $localSystemDbFallback
}

if (-not $MdbPath) {
    throw "GATE_MDB_PATH is not set."
}
if (-not (Test-Path -LiteralPath $MdbPath)) {
    throw "config.mdb not found: $MdbPath"
}
if (-not $SystemDbPath) {
    throw "GATE_SYSTEMDB_PATH is not set."
}
if (-not (Test-Path -LiteralPath $SystemDbPath)) {
    throw "SystemDB .mdw file not found: $SystemDbPath"
}
if (-not $Uid) {
    throw "GATE_MDB_UID is not set."
}

$hasPwd = $PSBoundParameters.ContainsKey("Pwd") -or $null -ne $env:GATE_MDB_PWD -or $null -ne $env:GATE_PWD
if (-not $hasPwd) {
    throw "GATE_MDB_PWD is not set."
}

if ($Top -lt 1) {
    throw "Top must be >= 1"
}

$tempMdb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-compare-copy-{0}.mdb" -f [System.Guid]::NewGuid().ToString("N"))
$tempSystemDb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-compare-systemdb-copy-{0}.mdw" -f [System.Guid]::NewGuid().ToString("N"))
try {
    Copy-Item -LiteralPath $MdbPath -Destination $tempMdb -Force
    Copy-Item -LiteralPath $SystemDbPath -Destination $tempSystemDb -Force
}
catch {
    throw "Failed to create temporary copies of Gate files. MDB: $MdbPath. MDW: $SystemDbPath. Error: $($_.Exception.Message)"
}

$pythonScript = @'
import collections
import re
import sys
from datetime import datetime

import pyodbc

mdb_path = sys.argv[1]
systemdb_path = sys.argv[2]
uid = sys.argv[3]
pwd = sys.argv[4]
left_needle = (sys.argv[5] if len(sys.argv) > 5 else "").strip()
right_needle = (sys.argv[6] if len(sys.argv) > 6 else "").strip()
if right_needle == "__EMPTY__":
    right_needle = ""
top = int(sys.argv[7])
preferred_driver = sys.argv[8]

PHONE_READER_HINTS = (
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
LOOKALIKE_MAP = {
    "A": "А",
    "B": "В",
    "C": "С",
    "E": "Е",
    "H": "Н",
    "K": "К",
    "M": "М",
    "O": "О",
    "P": "Р",
    "T": "Т",
    "X": "Х",
    "Y": "У",
}
USER_FIELDS = [
    "UserPtr",
    "KeyType",
    "KeyTypeName",
    "GroupPtr",
    "IdleNotLimited",
    "NoFacility",
    "Status",
    "BgPtr",
    "SendSms",
    "SendMail",
    "UniPassMode",
    "Phone",
    "Number",
    "NumberU",
    "NumberMifare",
    "LastName",
    "FirstName",
    "FatherName",
    "Visitor",
    "Deleted",
    "UseExpiry",
    "ExpiryDate",
    "ExpiryTime",
    "LastUsed",
    "LastUsedRdrName",
]
ACCESS_FIELDS = [
    "ReaderName",
    "DevPtr",
    "DeviceKeyType",
    "DeviceKeyTypeName",
    "InnerNum",
    "Always",
    "Schedule1",
    "Schedule2",
    "Schedule3",
    "Schedule4",
    "Schedule5",
    "Schedule6",
    "Schedule7",
    "RecordState",
    "APB",
    "Inside",
    "CardType",
    "CardCode",
    "NoEntry",
    "NoExit",
]


def pick_driver(preferred: str) -> str:
    candidates = [
        preferred,
        "Microsoft Access Driver (*.mdb, *.accdb)",
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


def driver_candidates(preferred: str) -> list[str]:
    candidates = [
        preferred,
        "Driver do Microsoft Access (*.mdb)",
        "Microsoft Access Driver (*.mdb)",
        "Microsoft Access-Treiber (*.mdb)",
        "Microsoft Access Driver (*.mdb, *.accdb)",
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


def connect_with_fallback(mdb_path: str, systemdb_path: str, uid: str, pwd: str, preferred: str):
    errors: list[str] = []
    for driver_name in driver_candidates(preferred):
        try:
            conn = pyodbc.connect(
                f"DRIVER={{{driver_name}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"
            )
            return conn, driver_name
        except pyodbc.Error as exc:
            errors.append(f"{driver_name}: {exc}")
    detail = "\n".join(errors) if errors else "No compatible MDB ODBC driver was found."
    raise RuntimeError(f"Failed to connect to Gate MDB with available ODBC drivers:\n{detail}")


def normalize_digits(value) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def normalize_phone_key(value) -> str:
    digits = normalize_digits(value)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return digits[1:]
    return digits


def normalize_text(value) -> str:
    if value is None:
        return ""
    compact = re.sub(r"[\s-]+", "", str(value).upper())
    return "".join(LOOKALIKE_MAP.get(ch, ch) for ch in compact)


def looks_like_phone_reader(name) -> bool:
    return any(hint in str(name or "").lower() for hint in PHONE_READER_HINTS)


def looks_like_phone_identity_number(value) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    digits = normalize_digits(raw)
    if len(digits) < 10:
        return False
    return not any(ch.isalpha() for ch in raw)


def is_phone_identity_user(user) -> bool:
    if not normalize_phone_key(getattr(user, "Phone", None)):
        return False
    return looks_like_phone_identity_number(getattr(user, "Number", None))


def is_phone_like_needle(needle: str) -> bool:
    raw = needle.strip()
    digits = normalize_phone_key(raw)
    return bool(digits) and len(digits) >= 10 and not any(ch.isalpha() for ch in raw)


def row_matches_needle(user, needle: str) -> bool:
    raw = needle.strip().lower()
    digits = normalize_digits(needle)
    phone_digits = normalize_phone_key(needle)
    text = normalize_text(needle)
    direct_fields = [
        user.UserPtr,
        user.KeyType,
        user.Phone,
        user.Number,
        user.NumberU,
        user.NumberMifare,
        user.LastName,
        user.FirstName,
        user.FatherName,
        user.LastUsedRdrName,
    ]
    if raw and any(raw in str(value or "").lower() for value in direct_fields):
        return True
    if digits and any(digits in normalize_digits(value) for value in direct_fields):
        return True
    if phone_digits and (
        phone_digits in normalize_phone_key(user.Phone) or phone_digits in normalize_phone_key(user.Number)
    ):
        return True
    if text and any(text in normalize_text(value) for value in direct_fields):
        return True
    return False


def build_key_type_names(cursor):
    try:
        rows = cursor.execute("SELECT * FROM KeyTypes").fetchall()
    except Exception:
        return {}
    mapping = {}
    for row in rows:
        try:
            key = int(row[0])
        except Exception:
            continue
        mapping[key] = str(row[1]) if len(row) > 1 else str(row[0])
    return mapping


def load_users(cursor):
    return cursor.execute(
        """
        SELECT
            UserPtr,
            KeyType,
            GroupPtr,
            IdleNotLimited,
            NoFacility,
            Status,
            BgPtr,
            SendSms,
            SendMail,
            UniPassMode,
            Phone,
            Number,
            NumberU,
            NumberMifare,
            LastName,
            FirstName,
            FatherName,
            Visitor,
            Deleted,
            UseExpiry,
            ExpiryDate,
            ExpiryTime,
            LastUsed,
            LastUsedRdrName
        FROM Users
        ORDER BY UserPtr DESC
        """
    ).fetchall()


def load_access_rows(cursor, user_ptr: int):
    return cursor.execute(
        """
        SELECT
            a.RdrPtr,
            r.Name AS ReaderName,
            r.DevPtr,
            d.KeyType AS DeviceKeyType,
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
            a.NoExit
        FROM (AccessTable AS a
            LEFT JOIN Readers AS r ON r.RdrPtr = a.RdrPtr)
            LEFT JOIN Devices AS d ON d.DevPtr = r.DevPtr
        WHERE a.UserPtr = ?
        ORDER BY a.RdrPtr
        """,
        (user_ptr,),
    ).fetchall()


def count_inner_num_conflicts(cursor, rdr_ptr: int, inner_num, user_ptr: int) -> int:
    if inner_num is None:
        return 0
    try:
        normalized_inner_num = int(inner_num)
    except (TypeError, ValueError):
        return 0
    row = cursor.execute(
        """
        SELECT Count(*) AS ConflictCount
        FROM AccessTable
        WHERE RdrPtr = ? AND InnerNum = ? AND UserPtr <> ?
        """,
        (int(rdr_ptr), normalized_inner_num, int(user_ptr)),
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(getattr(row, "ConflictCount", row[0]) or 0)
    except Exception:
        return 0


def format_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return repr(value)


def collect_matches(cursor, users, key_type_names, needle: str, top_limit: int):
    matched_users = [user for user in users if row_matches_needle(user, needle)]
    records = []
    for user in matched_users[: top_limit * 5]:
        access_rows = load_access_rows(cursor, int(user.UserPtr))
        records.append(
            {
                "user": user,
                "access_rows": access_rows,
                "gsm_rows": [row for row in access_rows if looks_like_phone_reader(getattr(row, "ReaderName", None))],
                "inner_num_conflicts": {
                    int(row.RdrPtr): count_inner_num_conflicts(cursor, int(row.RdrPtr), getattr(row, "InnerNum", None), int(user.UserPtr))
                    for row in access_rows
                    if getattr(row, "RdrPtr", None) is not None
                },
                "key_type_name": key_type_names.get(int(user.KeyType)) if getattr(user, "KeyType", None) is not None else None,
            }
        )
    return records[:top_limit]


def preferred_record(records, needle: str):
    if not records:
        return None
    phone_like = is_phone_like_needle(needle)

    def score(record):
        user = record["user"]
        gsm_rows = record["gsm_rows"]
        return (
            0 if (phone_like and is_phone_identity_user(user)) else 1,
            0 if gsm_rows else 1,
            0 if not bool(getattr(user, "Deleted", False)) else 1,
            -int(user.UserPtr),
        )

    return sorted(records, key=score)[0]


def print_record(label: str, record):
    user = record["user"]
    print(f"{label}: UserPtr={user.UserPtr} | KeyType={format_value(user.KeyType)} | KeyTypeName={format_value(record['key_type_name'])}")
    print(
        "  Users: "
        f"Phone={format_value(user.Phone)} | Number={format_value(user.Number)} | NumberU={format_value(user.NumberU)} | "
        f"NumberMifare={format_value(user.NumberMifare)}"
    )
    print(
        "  Users: "
        f"LastName={format_value(user.LastName)} | FirstName={format_value(user.FirstName)} | FatherName={format_value(user.FatherName)} | "
        f"Visitor={format_value(user.Visitor)} | Deleted={format_value(user.Deleted)}"
    )
    print(
        "  Users: "
        f"UseExpiry={format_value(user.UseExpiry)} | ExpiryDate={format_value(user.ExpiryDate)} | ExpiryTime={format_value(user.ExpiryTime)} | "
        f"LastUsed={format_value(user.LastUsed)} | LastUsedRdrName={format_value(user.LastUsedRdrName)}"
    )
    if not record["access_rows"]:
        print("  AccessTable: (no rows)")
        return
    for row in record["access_rows"]:
        print(
            "  AccessTable: "
            f"RdrPtr={format_value(row.RdrPtr)} | ReaderName={format_value(row.ReaderName)} | "
            f"DevPtr={format_value(row.DevPtr)} | DeviceKeyType={format_value(row.DeviceKeyType)} | "
            f"InnerNum={format_value(row.InnerNum)} | Always={format_value(row.Always)} | "
            f"Schedule1={format_value(row.Schedule1)} | Schedule2={format_value(row.Schedule2)} | "
            f"Schedule3={format_value(row.Schedule3)} | Schedule4={format_value(row.Schedule4)} | "
            f"Schedule5={format_value(row.Schedule5)} | Schedule6={format_value(row.Schedule6)} | "
            f"Schedule7={format_value(row.Schedule7)} | RecordState={format_value(row.RecordState)} | "
            f"APB={format_value(row.APB)} | Inside={format_value(row.Inside)} | "
            f"CardType={format_value(row.CardType)} | CardCode={format_value(row.CardCode)} | "
            f"NoEntry={format_value(row.NoEntry)} | NoExit={format_value(row.NoExit)} | "
            f"GSMReader={format_value(looks_like_phone_reader(row.ReaderName))}"
        )


def print_matches(title: str, records, needle: str):
    print(f"=== {title} ===")
    print(f"Needle: {needle!r}")
    if not records:
        print("(no rows)")
        print()
        return
    for index, record in enumerate(records, start=1):
        print_record(f"Match #{index}", record)
        print("-" * 80)
    print()


def print_analysis(title: str, record):
    print(f"=== {title} ===")
    if record is None:
        print("(no selected row)")
        print()
        return
    user = record["user"]
    warnings = []
    if not is_phone_identity_user(user):
        warnings.append("Selected row is not a phone-identity user; it may be a vehicle row with the same contact phone.")
    if bool(getattr(user, "Deleted", False)):
        warnings.append("Users.Deleted=True")
    if bool(getattr(user, "UseExpiry", False)) and getattr(user, "ExpiryDate", None) is not None:
        warnings.append("Users.UseExpiry=True; check whether the key is still inside the allowed time window.")
    if not record["gsm_rows"]:
        warnings.append("No GSM-like reader rows were found in AccessTable for this user.")
    for row in record["gsm_rows"]:
        if getattr(row, "DeviceKeyType", None) is not None and getattr(user, "KeyType", None) is not None:
            if row.DeviceKeyType != user.KeyType:
                warnings.append(
                    f"RdrPtr {row.RdrPtr}: Users.KeyType={user.KeyType!r} differs from Devices.KeyType={row.DeviceKeyType!r}."
                )
        conflict_count = record["inner_num_conflicts"].get(int(row.RdrPtr), 0)
        if conflict_count > 0:
            warnings.append(
                f"RdrPtr {row.RdrPtr}: InnerNum={row.InnerNum!r} is also used by {conflict_count} other AccessTable row(s)."
            )
        if not bool(getattr(row, "Always", False)) and not any(bool(getattr(row, f"Schedule{idx}", False)) for idx in range(1, 8)):
            warnings.append(f"RdrPtr {row.RdrPtr}: no active schedule flags and Always is not enabled.")
        if bool(getattr(row, "NoEntry", False)) or bool(getattr(row, "NoExit", False)):
            warnings.append(
                f"RdrPtr {row.RdrPtr}: NoEntry={row.NoEntry!r}, NoExit={row.NoExit!r}."
            )
        if getattr(row, "CardType", None) is None and not str(getattr(row, "CardCode", "") or "").strip():
            warnings.append(f"RdrPtr {row.RdrPtr}: CardType/CardCode are both empty.")
    if not warnings:
        print("No obvious red flags in the selected row.")
    else:
        for item in warnings:
            print(f"- {item}")
    print()


def print_diff(left_record, right_record, key_type_names):
    print("=== Selected User Diff ===")
    if left_record is None or right_record is None:
        print("(diff skipped because one side is missing)")
        print()
        return
    left_user = left_record["user"]
    right_user = right_record["user"]
    for field in USER_FIELDS:
        if field == "KeyTypeName":
            left_value = left_record["key_type_name"]
            right_value = right_record["key_type_name"]
        else:
            left_value = getattr(left_user, field, None)
            right_value = getattr(right_user, field, None)
        marker = "==" if left_value == right_value else "!="
        print(f"{field}: left={format_value(left_value)} | right={format_value(right_value)} | {marker}")
    print()

    print("=== Selected Access Diff ===")
    left_access = {int(row.RdrPtr): row for row in left_record["access_rows"]}
    right_access = {int(row.RdrPtr): row for row in right_record["access_rows"]}
    all_reader_ids = sorted(set(left_access) | set(right_access))
    if not all_reader_ids:
        print("(no access rows on either side)")
        print()
        return
    for reader_id in all_reader_ids:
        left_row = left_access.get(reader_id)
        right_row = right_access.get(reader_id)
        reader_name = None
        if left_row is not None:
            reader_name = left_row.ReaderName
        elif right_row is not None:
            reader_name = right_row.ReaderName
        print(f"-- RdrPtr={reader_id} ReaderName={format_value(reader_name)} GSMReader={format_value(looks_like_phone_reader(reader_name))} --")
        for field in ACCESS_FIELDS:
            if field == "DeviceKeyTypeName":
                left_value = key_type_names.get(int(left_row.DeviceKeyType)) if left_row is not None and getattr(left_row, "DeviceKeyType", None) is not None else None
                right_value = key_type_names.get(int(right_row.DeviceKeyType)) if right_row is not None and getattr(right_row, "DeviceKeyType", None) is not None else None
            else:
                left_value = getattr(left_row, field, None) if left_row is not None else None
                right_value = getattr(right_row, field, None) if right_row is not None else None
            marker = "==" if left_value == right_value else "!="
            print(f"{field}: left={format_value(left_value)} | right={format_value(right_value)} | {marker}")
        print()


conn, driver = connect_with_fallback(mdb_path, systemdb_path, uid, pwd, preferred_driver)
cur = conn.cursor()
key_type_names = build_key_type_names(cur)
users = load_users(cur)

left_records = collect_matches(cur, users, key_type_names, left_needle, top)
right_records = collect_matches(cur, users, key_type_names, right_needle, top) if right_needle else []

left_selected = preferred_record(left_records, left_needle)
right_selected = preferred_record(right_records, right_needle) if right_needle else None

print("=== Source ===")
print(f"MDB: {mdb_path}")
print(f"SystemDB: {systemdb_path}")
print(f"Driver: {driver}")
print()

print_matches("Left Matches", left_records, left_needle)
if right_needle:
    print_matches("Right Matches", right_records, right_needle)

print_analysis("Left Analysis", left_selected)
if right_needle:
    print_analysis("Right Analysis", right_selected)
    print_diff(left_selected, right_selected, key_type_names)

cur.close()
conn.close()
'@

$tempPy = [System.IO.Path]::GetTempFileName()
try {
    Set-Content -LiteralPath $tempPy -Value $pythonScript -Encoding UTF8
    $rightNeedleArg = if ([string]::IsNullOrWhiteSpace($RightNeedle)) { "__EMPTY__" } else { $RightNeedle }
    $pythonArgs = @()
    if ($PythonVersion) {
        $pythonArgs += $PythonVersion
    }
    $pythonArgs += @($tempPy, $tempMdb, $tempSystemDb, $Uid, $Pwd, $LeftNeedle, $rightNeedleArg, $Top.ToString(), $Driver)
    & $PythonLauncher @pythonArgs
}
finally {
    if (Test-Path -LiteralPath $tempPy) {
        Remove-Item -LiteralPath $tempPy -Force
    }
    if (Test-Path -LiteralPath $tempMdb) {
        Remove-Item -LiteralPath $tempMdb -Force
    }
    if (Test-Path -LiteralPath $tempSystemDb) {
        Remove-Item -LiteralPath $tempSystemDb -Force
    }
}
