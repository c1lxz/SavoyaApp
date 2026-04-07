param(
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [int]$Top = 5,
    [string]$PythonLauncher = "py",
    [string]$PythonVersion = "-3.12"
)

$ErrorActionPreference = "Stop"

if ($Top -lt 1) {
    throw "Top must be >= 1"
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"

if ((-not $DatabaseUrl) -and (Test-Path -LiteralPath $envFile)) {
    Get-Content -LiteralPath $envFile |
        Where-Object { $_ -match '^\s*[^#].*=.*$' } |
        ForEach-Object {
            $name, $value = $_ -split '=', 2
            $name = $name.Trim()
            $value = $value.Trim().Trim('"')
            Set-Item -Path "Env:$name" -Value $value
            if ($name -eq "DATABASE_URL") {
                $DatabaseUrl = $value
            }
        }
}

if (-not $DatabaseUrl) {
    throw "DATABASE_URL is not set. Put it in .env or pass -DatabaseUrl."
}

$pythonScript = @'
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote


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
        "Use a sqlite+aiosqlite:///... or sqlite:///... database."
    )


database_url = sys.argv[1]
top = int(sys.argv[2])
project_root = Path(sys.argv[3]).resolve()
db_path = resolve_sqlite_path(database_url, project_root)

if not db_path.exists():
    raise FileNotFoundError(f"SQLite database file not found: {db_path}")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute(
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
    (top,),
).fetchall()

print("=== Recent Pass Requests ===")
print(f"DB: {db_path}")
print()

if not rows:
    print("(no rows)")
    conn.close()
    raise SystemExit(0)

for row in rows:
    access_point_ids = row["access_point_ids"]
    try:
        parsed_ids = json.loads(access_point_ids) if isinstance(access_point_ids, str) else access_point_ids
    except Exception:
        parsed_ids = access_point_ids

    resident = row["resident_name"] or row["resident_login"] or row["resident_phone"] or f"user:{row['resident_id']}"

    print(f"RequestId: {row['id']}")
    print(f"Resident: {resident} (resident_id={row['resident_id']})")
    print(f"Status: {row['status']}")
    print(f"Key: type={row['key_type']} value={row['key_value']}")
    print(f"GateKeyId: {row['gate_key_id']}")
    print(f"Plot: {row['plot_number']}")
    print(f"Permanent: {bool(row['is_permanent'])}")
    print(f"AccessPointIds: {parsed_ids}")
    print(f"CreatedAt: {row['created_at']}")
    print(f"ExpiresAt: {row['expires_at']}")
    print(f"CancelledAt: {row['cancelled_at']}")
    print("-" * 60)

conn.close()
'@

$tempPy = [System.IO.Path]::GetTempFileName()
try {
    Set-Content -LiteralPath $tempPy -Value $pythonScript -Encoding UTF8
    $pythonArgs = @()
    if ($PythonVersion) {
        $pythonArgs += $PythonVersion
    }
    $pythonArgs += @($tempPy, $DatabaseUrl, $Top.ToString(), $projectRoot)
    & $PythonLauncher @pythonArgs
}
finally {
    if (Test-Path -LiteralPath $tempPy) {
        Remove-Item -LiteralPath $tempPy -Force
    }
}
