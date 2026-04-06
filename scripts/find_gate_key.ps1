param(
    [string]$Needle,
    [string]$MdbPath = $env:GATE_MDB_PATH,
    [string]$SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH }),
    [string]$Uid = $(if ($env:GATE_MDB_UID) { $env:GATE_MDB_UID } else { $env:GATE_UID }),
    [string]$Pwd = $(if ($null -ne $env:GATE_MDB_PWD) { $env:GATE_MDB_PWD } else { $env:GATE_PWD }),
    [string]$PythonLauncher = $(if ($env:GATE_PYTHON_LAUNCHER) { $env:GATE_PYTHON_LAUNCHER } else { "py" }),
    [string]$PythonVersion = $(if ($env:GATE_PYTHON_VERSION) { $env:GATE_PYTHON_VERSION } else { "-3.12-32" }),
    [string]$Driver = $(if ($env:GATE_ODBC_DRIVER) { $env:GATE_ODBC_DRIVER } else { "Driver do Microsoft Access (*.mdb)" }),
    [int]$Top = 20
)

$ErrorActionPreference = "Stop"

if (-not $Needle) {
    throw "Pass -Needle with phone digits or vehicle number fragment."
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

needle_digits = "".join(ch for ch in needle if ch.isdigit())
needle_upper = re.sub(r"\s+", "", needle.upper())

sql = f"""
SELECT TOP {top}
    k.id,
    k.user_id,
    k.key_type,
    k.key_value,
    k.valid_from,
    k.valid_to,
    k.is_blocked,
    u.last_name,
    u.first_name
FROM Keys k
LEFT JOIN Users u ON u.id = k.user_id
ORDER BY k.id DESC
"""

rows = cur.execute(sql).fetchall()
matches = []
for row in rows:
    key_value = "" if row.key_value is None else str(row.key_value)
    key_digits = "".join(ch for ch in key_value if ch.isdigit())
    key_upper = re.sub(r"\s+", "", key_value.upper())

    if needle_digits and needle_digits in key_digits:
        matches.append(row)
        continue
    if needle_upper and needle_upper in key_upper:
        matches.append(row)

print("=== Matching Keys ===")
if not matches:
    print("(no rows)")
else:
    for row in matches:
        print(tuple(row))

print()
print("=== Related Permissions ===")
if not matches:
    print("(no rows)")
else:
    user_ids = sorted({int(row.user_id) for row in matches if row.user_id is not None})
    if not user_ids:
        print("(no rows)")
    else:
        placeholders = ", ".join(["?"] * len(user_ids))
        perm_sql = f"""
        SELECT TOP {top}
            ap.id,
            ap.user_id,
            ap.access_point_id,
            ap.is_permanent,
            p.name
        FROM AccessPermissions ap
        LEFT JOIN AccessPoints p ON p.id = ap.access_point_id
        WHERE ap.user_id IN ({placeholders})
        ORDER BY ap.id DESC
        """
        for row in cur.execute(perm_sql, user_ids).fetchall():
            print(tuple(row))

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
