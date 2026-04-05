param(
    [string]$Needle,
    [string]$MdbPath = $env:GATE_MDB_PATH,
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
import re
import sys

import pyodbc

mdb_path = sys.argv[1]
needle = sys.argv[2].strip()
top = int(sys.argv[3])

conn = pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={mdb_path}")
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
    py -3.12 $tempPy $tempMdb $Needle $Top
}
finally {
    if (Test-Path -LiteralPath $tempPy) {
        Remove-Item -LiteralPath $tempPy -Force
    }
    if (Test-Path -LiteralPath $tempMdb) {
        Remove-Item -LiteralPath $tempMdb -Force
    }
}
