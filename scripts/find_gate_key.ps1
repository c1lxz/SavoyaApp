param(
    [string]$Needle,
    [string]$MdbPath = $env:GATE_MDB_PATH,
    [string]$SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH }),
    [string]$Uid = $(if ($env:GATE_MDB_UID) { $env:GATE_MDB_UID } else { $env:GATE_UID }),
    [string]$Pwd = $(if ($null -ne $env:GATE_MDB_PWD) { $env:GATE_MDB_PWD } else { $env:GATE_PWD }),
    [string]$PythonLauncher = $(if ($env:GATE_PYTHON_LAUNCHER) { $env:GATE_PYTHON_LAUNCHER } else { "py" }),
    [string]$PythonVersion = $(if ($env:GATE_PYTHON_VERSION) { $env:GATE_PYTHON_VERSION } else { "-3.12-32" }),
    [string]$Driver = $(if ($env:GATE_ODBC_DRIVER) { $env:GATE_ODBC_DRIVER } else { "Microsoft Access Driver (*.mdb, *.accdb)" }),
    [int]$Top = 20
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

if (-not $Needle) {
    throw "Pass -Needle with phone digits, car number, card fragment, or resident name."
}

if (-not $MdbPath) {
    throw "GATE_MDB_PATH is not set. Pass -MdbPath or set GATE_MDB_PATH in the environment."
}

if (-not (Test-Path -LiteralPath $MdbPath)) {
    throw "config.mdb not found: $MdbPath"
}

if (-not $SystemDbPath) {
    throw "GATE_SYSTEMDB_PATH is not set. Pass -SystemDbPath or set GATE_SYSTEMDB_PATH (or GATE_MDW_PATH) in the environment."
}

if (-not (Test-Path -LiteralPath $SystemDbPath)) {
    throw "SystemDB .mdw file not found: $SystemDbPath"
}

if (-not $Uid) {
    throw "GATE_MDB_UID is not set. Pass -Uid or set GATE_MDB_UID (or GATE_UID) in the environment."
}

$hasPwd = $PSBoundParameters.ContainsKey("Pwd") -or $null -ne $env:GATE_MDB_PWD -or $null -ne $env:GATE_PWD
if (-not $hasPwd) {
    throw "GATE_MDB_PWD is not set. Pass -Pwd (use -Pwd '' for an empty password) or set GATE_MDB_PWD (or GATE_PWD) in the environment."
}

if ($Top -lt 1) {
    throw "Top must be >= 1"
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
import re
import sys

import pyodbc

mdb_path = sys.argv[1]
systemdb_path = sys.argv[2]
uid = sys.argv[3]
pwd = sys.argv[4]
needle = sys.argv[5].strip()
top = int(sys.argv[6])
preferred_driver = sys.argv[7]


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


def normalize_text(value) -> str:
    if value is None:
        return ""
    compact = re.sub(r"[\s-]+", "", str(value).upper())
    return "".join(LOOKALIKE_MAP.get(ch, ch) for ch in compact)


driver = pick_driver(preferred_driver)
conn = pyodbc.connect(
    f"DRIVER={{{driver}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"
)
cur = conn.cursor()

needle_digits = normalize_digits(needle)
needle_upper = normalize_text(needle)

users = cur.execute(
    f"""
    SELECT TOP {top * 50}
        UserPtr,
        Phone,
        Number,
        NumberU,
        NumberMifare,
        LastName,
        FirstName,
        Visitor,
        Deleted,
        UseExpiry,
        ExpiryDate,
        ExpiryTime
    FROM Users
    ORDER BY UserPtr DESC
    """
).fetchall()

matches = []
for row in users:
    fields = [row.Phone, row.Number, row.NumberU, row.NumberMifare, row.LastName, row.FirstName]
    normalized_digits = [normalize_digits(item) for item in fields]
    normalized_text = [normalize_text(item) for item in fields]

    if needle_digits and any(needle_digits in item for item in normalized_digits if item):
        matches.append(row)
        continue
    if needle_upper and any(needle_upper in item for item in normalized_text if item):
        matches.append(row)

print("=== Matching Users ===")
if not matches:
    print("(no rows)")
else:
    for row in matches[:top]:
        print(tuple(row))

print()
print("=== Related Access ===")
if not matches:
    print("(no rows)")
else:
    seen = set()
    for row in matches[:top]:
        user_ptr = int(row.UserPtr)
        if user_ptr in seen:
            continue
        seen.add(user_ptr)
        print(f"-- UserPtr={user_ptr} --")
        perms = cur.execute(
            f"""
            SELECT TOP {top}
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
            user_ptr,
        ).fetchall()
        if not perms:
            print("(no rows)")
        else:
            for perm in perms:
                print(tuple(perm))
        print()

cur.close()
conn.close()
'@

$tempPy = [System.IO.Path]::GetTempFileName()
try {
    Set-Content -LiteralPath $tempPy -Value $pythonScript -Encoding UTF8
    $pythonArgs = @()
    if ($PythonVersion) {
        $pythonArgs += $PythonVersion
    }
    $pythonArgs += @($tempPy, $tempMdb, $tempSystemDb, $Uid, $Pwd, $Needle, $Top.ToString(), $Driver)
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
