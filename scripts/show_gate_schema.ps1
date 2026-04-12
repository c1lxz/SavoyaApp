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


def arg(index: int, default: str = "") -> str:
    return sys.argv[index] if len(sys.argv) > index else default


mdb_path = arg(1)
systemdb_path = arg(2)
uid = arg(3)
pwd = arg(4)
top = int(arg(5, "5"))
preferred_driver = arg(6)
tables_arg = arg(7)
name_pattern = arg(8).strip().lower()
include_samples = arg(9, "false").lower() == "true"


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


def describe_columns(cur, table_name: str):
    # Some real Gate MDB files expose malformed metadata through SQLColumns,
    # which makes pyodbc.cur.columns(...) crash during unicode decoding.
    # Read the schema through a zero-row SELECT instead.
    try:
        cur.execute(f"SELECT TOP 0 * FROM {quote_ident(table_name)}")
    except Exception as exc:
        raise RuntimeError(f"Failed to read schema for table {table_name!r}: {exc}") from exc
    description = cur.description or []
    columns = []
    for ordinal, column in enumerate(description, start=1):
        name, type_code, display_size, internal_size, precision, scale, null_ok = column
        columns.append(
            {
                "name": name,
                "type_code": type_code,
                "display_size": display_size,
                "internal_size": internal_size,
                "precision": precision,
                "scale": scale,
                "null_ok": null_ok,
                "ordinal": ordinal,
            }
        )
    return columns


driver = pick_driver(preferred_driver)
conn = pyodbc.connect(
    f"DRIVER={{{driver}}};DBQ={mdb_path};SystemDB={systemdb_path};UID={uid};PWD={pwd}"
)
cur = conn.cursor()

requested_tables = set()
for chunk in tables_arg.split("|"):
    for item in chunk.split(","):
        normalized = item.strip().lower()
        if normalized:
            requested_tables.add(normalized)

all_tables = []
for row in cur.tables():
    if str(getattr(row, "table_type", "")).upper() == "TABLE":
        all_tables.append(str(row.table_name))

table_names = sorted(set(all_tables))
if requested_tables:
    table_names = [name for name in table_names if name.lower() in requested_tables]
elif name_pattern:
    table_names = [name for name in table_names if name_pattern in name.lower()]

print("=== Gate Tables ===")
for name in table_names:
    print(name)
print()

if not table_names:
    if requested_tables:
        print("Requested tables:")
        for name in sorted(requested_tables):
            print(name)
        print()
        print("Available tables:")
        for name in sorted(set(all_tables)):
            print(name)
        print()
    print("(no matching tables)")
    cur.close()
    conn.close()
    raise SystemExit(0)

for table_name in table_names:
    print(f"=== {table_name} :: Columns ===")
    columns = describe_columns(cur, table_name)
    if not columns:
        print("(no columns)")
    else:
        for column in columns:
            print(
                f"{column['name']} | "
                f"type_code={column['type_code']!r} display_size={column['display_size']!r} "
                f"internal_size={column['internal_size']!r} precision={column['precision']!r} "
                f"scale={column['scale']!r} nullable={column['null_ok']!r} ordinal={column['ordinal']!r}"
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
