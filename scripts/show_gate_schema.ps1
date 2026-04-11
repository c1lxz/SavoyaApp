param(
    [string]$MdbPath = $env:GATE_MDB_PATH,
    [string]$SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH }),
    [string]$Uid = $(if ($env:GATE_MDB_UID) { $env:GATE_MDB_UID } else { $env:GATE_UID }),
    [string]$Pwd = $(if ($null -ne $env:GATE_MDB_PWD) { $env:GATE_MDB_PWD } else { $env:GATE_PWD }),
    [string]$PythonLauncher = $(if ($env:GATE_PYTHON_LAUNCHER) { $env:GATE_PYTHON_LAUNCHER } else { "py" }),
    [string]$PythonVersion = $(if ($env:GATE_PYTHON_VERSION) { $env:GATE_PYTHON_VERSION } else { "-3.12-32" }),
    [string]$Driver = $(if ($env:GATE_ODBC_DRIVER) { $env:GATE_ODBC_DRIVER } else { "Driver do Microsoft Access (*.mdb)" }),
    [string[]]$Tables,
    [string]$NamePattern,
    [switch]$IncludeSamples,
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

$tempMdb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-schema-copy-{0}.mdb" -f [System.Guid]::NewGuid().ToString("N"))
$tempSystemDb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-schema-systemdb-copy-{0}.mdw" -f [System.Guid]::NewGuid().ToString("N"))
try {
    Copy-Item -LiteralPath $MdbPath -Destination $tempMdb -Force
    Copy-Item -LiteralPath $SystemDbPath -Destination $tempSystemDb -Force
}
catch {
    throw "Failed to create temporary copies of Gate files. MDB: $MdbPath. MDW: $SystemDbPath. Error: $($_.Exception.Message)"
}

$tablesArg = if ($Tables) { ($Tables -join "|") } else { "" }
$namePatternArg = if ($null -ne $NamePattern) { [string]$NamePattern } else { "" }

$pythonScript = @'
import sys

import pyodbc

mdb_path = sys.argv[1]
systemdb_path = sys.argv[2]
uid = sys.argv[3]
pwd = sys.argv[4]
top = int(sys.argv[5])
preferred_driver = sys.argv[6]
tables_arg = sys.argv[7]
name_pattern = sys.argv[8].strip().lower()
include_samples = sys.argv[9].lower() == "true"


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


def quote_ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


driver = pick_driver(preferred_driver)
conn = pyodbc.connect(
    f"DRIVER={{{driver}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"
)
cur = conn.cursor()

requested_tables = {item.strip() for item in tables_arg.split("|") if item.strip()}

all_tables = []
for row in cur.tables():
    if str(getattr(row, "table_type", "")).upper() == "TABLE":
        all_tables.append(str(row.table_name))

table_names = sorted(set(all_tables))
if requested_tables:
    table_names = [name for name in table_names if name in requested_tables]
elif name_pattern:
    table_names = [name for name in table_names if name_pattern in name.lower()]

print("=== Gate Tables ===")
for name in table_names:
    print(name)
print()

if not table_names:
    print("(no matching tables)")
    cur.close()
    conn.close()
    raise SystemExit(0)

for table_name in table_names:
    print(f"=== {table_name} :: Columns ===")
    columns = list(cur.columns(table=table_name))
    if not columns:
        print("(no columns)")
    else:
        for column in columns:
            print(
                f"{column.column_name} | "
                f"type={column.type_name!r} size={column.column_size!r} "
                f"nullable={column.nullable!r} ordinal={column.ordinal_position!r}"
            )
    print()

    if include_samples:
        print(f"=== {table_name} :: Top {top} Rows ===")
        try:
            rows = cur.execute(f"SELECT TOP {top} * FROM {quote_ident(table_name)}").fetchall()
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
    $pythonArgs += @(
        $tempPy,
        $tempMdb,
        $tempSystemDb,
        $Uid,
        $Pwd,
        $Top.ToString(),
        $Driver,
        $tablesArg,
        $namePatternArg,
        $IncludeSamples.IsPresent.ToString()
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
