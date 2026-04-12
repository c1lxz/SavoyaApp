param(
    [string]$MdbPath = $env:GATE_MDB_PATH,
    [string]$SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH }),
    [string]$Uid = $(if ($env:GATE_MDB_UID) { $env:GATE_MDB_UID } else { $env:GATE_UID }),
    [string]$Pwd = $(if ($null -ne $env:GATE_MDB_PWD) { $env:GATE_MDB_PWD } else { $env:GATE_PWD }),
    [string]$PythonLauncher = $(if ($env:GATE_PYTHON_LAUNCHER) { $env:GATE_PYTHON_LAUNCHER } else { "py" }),
    [string]$PythonVersion = $(if ($env:GATE_PYTHON_VERSION) { $env:GATE_PYTHON_VERSION } else { "-3.12-32" }),
    [string]$Driver = $(if ($env:GATE_ODBC_DRIVER) { $env:GATE_ODBC_DRIVER } else { "Driver do Microsoft Access (*.mdb)" }),
    [string]$Needle,
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

$tempMdb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-gsm-users-copy-{0}.mdb" -f [System.Guid]::NewGuid().ToString("N"))
$tempSystemDb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-gsm-users-systemdb-copy-{0}.mdw" -f [System.Guid]::NewGuid().ToString("N"))
try {
    Copy-Item -LiteralPath $MdbPath -Destination $tempMdb -Force
    Copy-Item -LiteralPath $SystemDbPath -Destination $tempSystemDb -Force
}
catch {
    throw "Failed to create temporary copies of Gate files. MDB: $MdbPath. MDW: $SystemDbPath. Error: $($_.Exception.Message)"
}

$pythonScript = @'
import collections
import sys

import pyodbc

mdb_path = sys.argv[1]
systemdb_path = sys.argv[2]
uid = sys.argv[3]
pwd = sys.argv[4]
top = int(sys.argv[5])
preferred_driver = sys.argv[6]
needle = (sys.argv[7] if len(sys.argv) > 7 else "").strip().lower()


def pick_driver(preferred: str) -> str:
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


driver = pick_driver(preferred_driver)
conn = pyodbc.connect(
    f"DRIVER={{{driver}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"
)
cur = conn.cursor()

phone_reader_hints = ("gsm", "gate terminal", "terminal", "phone", "call", "caller", "tel", "звон", "вызов", "тел")
rows = cur.execute(
    f"""
    SELECT TOP {top * 10}
        u.UserPtr,
        u.KeyType,
        u.Phone,
        u.Number,
        u.LastName,
        u.FirstName,
        u.FatherName,
        u.Visitor,
        u.Deleted,
        u.UseExpiry,
        u.ExpiryDate,
        u.ExpiryTime,
        a.RdrPtr,
        r.Name,
        d.KeyType AS DeviceKeyType,
        a.Always,
        a.Schedule1,
        a.RecordState,
        a.CardType,
        a.CardCode,
        a.NoEntry,
        a.NoExit
    FROM ((Users AS u
        INNER JOIN AccessTable AS a ON a.UserPtr = u.UserPtr)
        LEFT JOIN Readers AS r ON r.RdrPtr = a.RdrPtr)
        LEFT JOIN Devices AS d ON d.DevPtr = r.DevPtr
    ORDER BY u.UserPtr DESC, a.RdrPtr ASC
    """
).fetchall()

rows = [
    row for row in rows
    if any(hint in str(row.Name or "").lower() for hint in phone_reader_hints)
]
if needle:
    rows = [
        row for row in rows
        if needle in str(row.Phone or "").lower()
        or needle in str(row.Number or "").lower()
        or needle in str(row.LastName or "").lower()
        or needle in str(row.FirstName or "").lower()
        or needle in str(row.Name or "").lower()
        or needle in str(row.RdrPtr or "").lower()
        or needle in str(row.UserPtr or "").lower()
    ]

print("=== GSM Gate Users ===")
if not rows:
    print("(no rows)")
    cur.close()
    conn.close()
    raise SystemExit(0)

grouped = collections.OrderedDict()
for row in rows:
    grouped.setdefault(int(row.UserPtr), []).append(row)

count = 0
for user_ptr, user_rows in grouped.items():
    if count >= top:
        break
    head = user_rows[0]
    print(
        f"UserPtr={head.UserPtr} | KeyType={head.KeyType!r} | "
        f"Phone={head.Phone!r} | Number={head.Number!r} | "
        f"LastName={head.LastName!r} | FirstName={head.FirstName!r} | FatherName={head.FatherName!r} | "
        f"Visitor={head.Visitor!r} | Deleted={head.Deleted!r} | "
        f"UseExpiry={head.UseExpiry!r} | ExpiryDate={head.ExpiryDate!r} | ExpiryTime={head.ExpiryTime!r}"
    )
    for access_row in user_rows:
        print(
            f"  Phone Reader: RdrPtr={access_row.RdrPtr} Name={access_row.Name!r} "
            f"DeviceKeyType={access_row.DeviceKeyType!r} Always={access_row.Always!r} "
            f"Schedule1={access_row.Schedule1!r} RecordState={access_row.RecordState!r} "
            f"CardType={access_row.CardType!r} CardCode={access_row.CardCode!r} "
            f"NoEntry={access_row.NoEntry!r} NoExit={access_row.NoExit!r}"
        )
    print("-" * 60)
    count += 1

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
    $pythonArgs += @($tempPy, $tempMdb, $tempSystemDb, $Uid, $Pwd, $Top.ToString(), $Driver, $Needle)
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
