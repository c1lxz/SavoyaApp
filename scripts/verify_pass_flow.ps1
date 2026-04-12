param(
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$Needle,
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

if ($Top -lt 1) {
    throw "Top must be >= 1"
}

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

if (-not $DatabaseUrl) {
    $DatabaseUrl = $env:DATABASE_URL
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

if (-not $DatabaseUrl) {
    throw "DATABASE_URL is not set. Pass -DatabaseUrl or define it in .env."
}

if (-not $MdbPath) {
    throw "GATE_MDB_PATH is not set. Pass -MdbPath or define it in .env."
}

if (-not (Test-Path -LiteralPath $MdbPath)) {
    throw "config.mdb not found: $MdbPath"
}

if (-not $SystemDbPath) {
    throw "GATE_SYSTEMDB_PATH is not set. Pass -SystemDbPath or define it in .env."
}

if (-not (Test-Path -LiteralPath $SystemDbPath)) {
    throw "SystemDB .mdw file not found: $SystemDbPath"
}

if (-not $Uid) {
    throw "GATE_MDB_UID is not set. Pass -Uid or define it in .env."
}

$hasPwd = $PSBoundParameters.ContainsKey("Pwd") -or $null -ne $env:GATE_MDB_PWD -or $null -ne $env:GATE_PWD
if (-not $hasPwd) {
    throw "GATE_MDB_PWD is not set. Pass -Pwd (use -Pwd '' for an empty password) or define it in .env."
}

$tempMdb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-config-copy-{0}.mdb" -f [System.Guid]::NewGuid().ToString("N"))
$tempSystemDb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-systemdb-copy-{0}.mdw" -f [System.Guid]::NewGuid().ToString("N"))
try {
    Copy-Item -LiteralPath $MdbPath -Destination $tempMdb -Force
    Copy-Item -LiteralPath $SystemDbPath -Destination $tempSystemDb -Force
}
catch {
    throw "Failed to create temporary copies of Gate files. MDB: $MdbPath. MDW: $SystemDbPath. Error: $($_.Exception.Message)"
}

$pythonScript = @'
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote

import pyodbc


def resolve_sqlite_path(database_url: str, project_root: Path) -> Path:
    prefixes = ("sqlite+aiosqlite:///", "sqlite:///")
    for prefix in prefixes:
        if database_url.startswith(prefix):
            raw = unquote(database_url[len(prefix):])
            path = Path(raw)
            if not path.is_absolute():
                path = (project_root / path).resolve()
            return path
    raise RuntimeError(
        f"Unsupported DATABASE_URL for this diagnostic script: {database_url}. "
        "Use sqlite+aiosqlite:///... or sqlite:///..."
    )


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


LOOKALIKE_MAP = {
    "A": "\u0410",
    "B": "\u0412",
    "C": "\u0421",
    "E": "\u0415",
    "H": "\u041d",
    "K": "\u041a",
    "M": "\u041c",
    "O": "\u041e",
    "P": "\u0420",
    "T": "\u0422",
    "X": "\u0425",
    "Y": "\u0423",
    "\u0410": "\u0410",
    "\u0412": "\u0412",
    "\u0421": "\u0421",
    "\u0415": "\u0415",
    "\u041d": "\u041d",
    "\u041a": "\u041a",
    "\u041c": "\u041c",
    "\u041e": "\u041e",
    "\u0420": "\u0420",
    "\u0422": "\u0422",
    "\u0425": "\u0425",
    "\u0423": "\u0423",
}


def normalize_digits(value) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def normalize_phone_key(value) -> str:
    digits = normalize_digits(value)
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith(("7", "8")):
        return f"00{digits[1:]}"
    if len(digits) == 10 and digits.startswith("9"):
        return f"00{digits}"
    return digits


def normalize_text(value) -> str:
    if value is None:
        return ""
    compact = re.sub(r"[\s-]+", "", str(value).upper())
    return "".join(LOOKALIKE_MAP.get(ch, ch) for ch in compact)


def parse_request_rows(sqlite_conn: sqlite3.Connection, top: int, needle: str | None):
    limit = max(top * 50, 200)
    rows = sqlite_conn.execute(
        """
        SELECT
            r.id,
            r.resident_id,
            r.key_type,
            r.key_value,
            r.gate_key_id,
            r.access_point_ids,
            r.is_permanent,
            r.expires_at,
            r.status,
            r.created_at,
            r.cancelled_at,
            r.plot_number,
            u.name AS resident_name,
            u.login AS resident_login,
            u.phone AS resident_phone
        FROM requests AS r
        LEFT JOIN users AS u ON u.id = r.resident_id
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not needle:
        return rows[:top]

    needle_text = normalize_text(needle)
    needle_digits = normalize_digits(needle)

    filtered = []
    for row in rows:
        haystacks = [
            row["key_value"],
            row["resident_name"],
            row["resident_login"],
            row["resident_phone"],
        ]
        text_match = needle_text and any(needle_text in normalize_text(value) for value in haystacks if value is not None)
        digits_match = needle_digits and any(needle_digits in normalize_digits(value) for value in haystacks if value is not None)
        if text_match or digits_match:
            filtered.append(row)
    return filtered[:top]


def load_gate_users(gate_cursor):
    return gate_cursor.execute(
        """
        SELECT
            UserPtr,
            KeyType,
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


def find_gate_user(users, request_row):
    gate_key_id = request_row["gate_key_id"]
    key_type = request_row["key_type"] or ""
    key_value = request_row["key_value"] or ""

    if gate_key_id is not None:
        for row in users:
            if int(row.UserPtr) == int(gate_key_id):
                return "gate_key_id", row

    target_digits = normalize_digits(key_value)
    target_text = normalize_text(key_value)
    for row in users:
        if key_type == "Phone":
            if target_digits and normalize_phone_key(row.Phone) == normalize_phone_key(target_digits):
                return "phone", row
        else:
            if target_text and normalize_text(row.Number) == target_text:
                return "number", row

    return None, None


def load_access_rows(gate_cursor, user_ptr: int):
    return gate_cursor.execute(
        """
        SELECT
            a.UserPtr,
            a.RdrPtr,
            r.Name,
            a.Always,
            a.Schedule1,
            a.Schedule2,
            a.Schedule3,
            a.Schedule4,
            a.Schedule5,
            a.Schedule6,
            a.Schedule7,
            a.NoEntry,
            a.NoExit
        FROM AccessTable AS a
        LEFT JOIN Readers AS r ON r.RdrPtr = a.RdrPtr
        WHERE a.UserPtr = ?
        ORDER BY a.RdrPtr
        """,
        (user_ptr,),
    ).fetchall()


database_url = sys.argv[1]
mdb_path = sys.argv[2]
systemdb_path = sys.argv[3]
uid = sys.argv[4]
pwd = sys.argv[5]
top = int(sys.argv[6])
preferred_driver = sys.argv[7]
needle = sys.argv[8] if len(sys.argv) > 8 and sys.argv[8] else None
project_root = Path(sys.argv[9]).resolve()

sqlite_path = resolve_sqlite_path(database_url, project_root)
if not sqlite_path.exists():
    raise FileNotFoundError(f"SQLite database file not found: {sqlite_path}")

sqlite_conn = sqlite3.connect(sqlite_path)
sqlite_conn.row_factory = sqlite3.Row

driver = pick_driver(preferred_driver)
gate_conn = pyodbc.connect(
    f"DRIVER={{{driver}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"
)
gate_cursor = gate_conn.cursor()

request_rows = parse_request_rows(sqlite_conn, top, needle)
gate_users = load_gate_users(gate_cursor)

print("=== Backend Requests -> Gate Check ===")
print(f"Backend DB: {sqlite_path}")
print(f"Gate MDB: {mdb_path}")
print()

if not request_rows:
    print("(no rows)")
else:
    for row in request_rows:
        print(f"RequestId: {row['id']}")
        print(f"BackendKey: type={row['key_type']} value={row['key_value']!r}")
        print(
            "BackendStatus: "
            f"status={row['status']} gate_key_id={row['gate_key_id']} "
            f"created_at={row['created_at']} expires_at={row['expires_at']}"
        )
        print(f"Resident: {row['resident_name'] or row['resident_login'] or row['resident_phone'] or ('user:' + str(row['resident_id']))}")
        print(f"Plot: {row['plot_number']}")
        print(f"AccessPointIds: {row['access_point_ids']}")

        match_kind, gate_user = find_gate_user(gate_users, row)
        if gate_user is None:
            print("GateMatch: NOT FOUND")
            print("-" * 60)
            continue

        print(
            "GateMatch: FOUND "
            f"(by {match_kind}) UserPtr={gate_user.UserPtr} Deleted={gate_user.Deleted!r} Visitor={gate_user.Visitor!r} "
            f"KeyType={gate_user.KeyType!r} Number={gate_user.Number!r} Phone={gate_user.Phone!r}"
        )
        print(
            f"GateName: LastName={gate_user.LastName!r} FirstName={gate_user.FirstName!r} FatherName={gate_user.FatherName!r}"
        )
        print(
            f"GateExpiry: UseExpiry={gate_user.UseExpiry!r} ExpiryDate={gate_user.ExpiryDate!r} ExpiryTime={gate_user.ExpiryTime!r}"
        )

        access_rows = load_access_rows(gate_cursor, int(gate_user.UserPtr))
        if not access_rows:
            print("GateAccess: (no rows)")
        else:
            print("GateAccess:")
            for access_row in access_rows:
                print(
                    f"  RdrPtr={access_row.RdrPtr} Name={access_row.Name!r} "
                    f"Always={access_row.Always!r} NoEntry={access_row.NoEntry!r} NoExit={access_row.NoExit!r}"
                )
            gsm_rows = [access_row for access_row in access_rows if "gsm" in str(access_row.Name or "").lower()]
            print(f"GsmAccess: {'YES' if gsm_rows else 'NO'}")
        print("-" * 60)

gate_cursor.close()
gate_conn.close()
sqlite_conn.close()
'@

$tempPy = [System.IO.Path]::GetTempFileName()
try {
    Set-Content -LiteralPath $tempPy -Value $pythonScript -Encoding UTF8
    $pythonArgs = @()
    if ($PythonVersion) {
        $pythonArgs += $PythonVersion
    }
    $pythonArgs += @(
        $tempPy,
        $DatabaseUrl,
        $tempMdb,
        $tempSystemDb,
        $Uid,
        $Pwd,
        $Top.ToString(),
        $Driver,
        $Needle,
        $projectRoot
    )
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
