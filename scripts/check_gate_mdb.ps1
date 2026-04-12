param(
    [string]$MdbPath = $env:GATE_MDB_PATH,
    [string]$SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH }),
    [string]$Uid = $(if ($env:GATE_MDB_UID) { $env:GATE_MDB_UID } else { $env:GATE_UID }),
    [string]$Pwd = $(if ($null -ne $env:GATE_MDB_PWD) { $env:GATE_MDB_PWD } else { $env:GATE_PWD }),
    [string]$PythonLauncher = $(if ($env:GATE_PYTHON_LAUNCHER) { $env:GATE_PYTHON_LAUNCHER } else { "py" }),
    [string]$PythonVersion = $(if ($env:GATE_PYTHON_VERSION) { $env:GATE_PYTHON_VERSION } else { "-3.12-32" }),
    [string]$Driver = $(if ($env:GATE_ODBC_DRIVER) { $env:GATE_ODBC_DRIVER } else { "Microsoft Access Driver (*.mdb, *.accdb)" }),
    [int]$Top = 10
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
import sys

import pyodbc

mdb_path = sys.argv[1]
systemdb_path = sys.argv[2]
uid = sys.argv[3]
pwd = sys.argv[4]
top = int(sys.argv[5])
preferred_driver = sys.argv[6]


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


driver = pick_driver(preferred_driver)
conn = pyodbc.connect(
    f"DRIVER={{{driver}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"
)
cur = conn.cursor()

print("=== Tables ===")
tables = []
for row in cur.tables():
    if str(getattr(row, "table_type", "")).upper() == "TABLE":
        tables.append(str(row.table_name))
for name in sorted(set(tables)):
    print(name)
print()

queries = [
    ("Readers", f"SELECT TOP {top} RdrPtr, Name, DevPtr, Locked FROM Readers ORDER BY RdrPtr DESC"),
    (
        "Users",
        f"SELECT TOP {top} UserPtr, Phone, Number, NumberU, NumberMifare, LastName, FirstName, Visitor, Deleted, UseExpiry, ExpiryDate, ExpiryTime FROM Users ORDER BY UserPtr DESC",
    ),
    (
        "AccessTable",
        f"SELECT TOP {top} a.UserPtr, a.RdrPtr, r.Name, a.Always, a.Schedule1, a.Schedule2, a.Schedule3, a.Schedule4, a.Schedule5, a.Schedule6, a.Schedule7, a.NoEntry, a.NoExit FROM AccessTable AS a LEFT JOIN Readers AS r ON r.RdrPtr = a.RdrPtr ORDER BY a.UserPtr DESC, a.RdrPtr DESC",
    ),
    ("AccessZones", f"SELECT TOP {top} ZonePtr, ZoneName FROM AccessZones ORDER BY ZonePtr DESC"),
    ("KeyTypes", f"SELECT TOP {top} * FROM KeyTypes"),
]

for title, sql in queries:
    print(f"=== {title} ===")
    try:
        rows = cur.execute(sql).fetchall()
        if not rows:
            print("(no rows)")
        else:
            for row in rows:
                print(tuple(row))
    except Exception as exc:
        print(f"ERROR: {exc}")
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
    $pythonArgs += @($tempPy, $tempMdb, $tempSystemDb, $Uid, $Pwd, $Top.ToString(), $Driver)
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
