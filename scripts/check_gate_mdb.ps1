param(
    [string]$MdbPath = $env:GATE_MDB_PATH,
    [int]$Top = 10
)

$ErrorActionPreference = "Stop"

if (-not $MdbPath) {
    throw "GATE_MDB_PATH is not set. Pass -MdbPath or set GATE_MDB_PATH in the environment."
}

if (-not (Test-Path -LiteralPath $MdbPath)) {
    throw "config.mdb not found: $MdbPath"
}

if ($Top -lt 1) {
    throw "Top must be >= 1"
}

$tempMdb = Join-Path ([System.IO.Path]::GetTempPath()) ("gate-config-copy-{0}.mdb" -f [System.Guid]::NewGuid().ToString("N"))
try {
    Copy-Item -LiteralPath $MdbPath -Destination $tempMdb -Force
}
catch {
    throw "Failed to create temporary copy of config.mdb. Original file may be locked too aggressively or access is denied. Path: $MdbPath. Error: $($_.Exception.Message)"
}

$pythonScript = @'
import json
import os
import sys

import pyodbc

mdb_path = sys.argv[1]
top = int(sys.argv[2])

conn = pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={mdb_path}")
cur = conn.cursor()

queries = [
    ("AccessPoints", f"SELECT TOP {top} id, name FROM AccessPoints ORDER BY id DESC"),
    ("Users", f"SELECT TOP {top} id, last_name, first_name, is_visitor, created_at FROM Users ORDER BY id DESC"),
    ("Keys", f"SELECT TOP {top} id, user_id, key_type, key_value, valid_from, valid_to, is_blocked FROM Keys ORDER BY id DESC"),
    ("AccessPermissions", f"SELECT TOP {top} id, user_id, access_point_id, is_permanent FROM AccessPermissions ORDER BY id DESC"),
    ("WiegandCredentials", f"SELECT TOP {top} id, key_id, user_id, access_point_id, facility_code, card_number, wiegand_payload, created_at FROM WiegandCredentials ORDER BY id DESC"),
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
    py -3.12 $tempPy $tempMdb $Top
}
finally {
    if (Test-Path -LiteralPath $tempPy) {
        Remove-Item -LiteralPath $tempPy -Force
    }
    if (Test-Path -LiteralPath $tempMdb) {
        Remove-Item -LiteralPath $tempMdb -Force
    }
}
