param(
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$Needle,
    [string]$PythonLauncher = "py",
    [string]$PythonVersion = "-3.12"
)

$ErrorActionPreference = "Stop"

if (-not $Needle) {
    throw "Pass -Needle with phone digits, car number, login, or resident name."
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
import re
import sqlite3
import sys
from datetime import datetime, timezone
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
        f"Unsupported DATABASE_URL for this script: {database_url}. "
        "Use sqlite+aiosqlite:///... or sqlite:///..."
    )


def normalize_digits(value) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def normalize_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value).upper())


database_url = sys.argv[1]
needle = sys.argv[2].strip()
project_root = Path(sys.argv[3]).resolve()
db_path = resolve_sqlite_path(database_url, project_root)

if not db_path.exists():
    raise FileNotFoundError(f"SQLite database file not found: {db_path}")

needle_digits = normalize_digits(needle)
needle_text = normalize_text(needle)

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
        r.status,
        r.created_at,
        r.cancelled_at,
        u.name AS resident_name,
        u.login AS resident_login,
        u.phone AS resident_phone
    FROM requests AS r
    LEFT JOIN users AS u ON u.id = r.resident_id
    WHERE r.status = 'active'
    ORDER BY r.id DESC
    """
).fetchall()

matches = []
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
        matches.append(row)

print(f"DB: {db_path}")
print(f"Needle: {needle}")
print()

if not matches:
    print("No active requests matched.")
    conn.close()
    raise SystemExit(0)

cancelled_at = datetime.now(timezone.utc).isoformat()
ids = [int(row["id"]) for row in matches]
conn.executemany(
    "UPDATE requests SET status = 'cancelled', cancelled_at = ? WHERE id = ? AND status = 'active'",
    [(cancelled_at, request_id) for request_id in ids],
)
conn.commit()

print("Cancelled requests:")
for row in matches:
    resident = row["resident_name"] or row["resident_login"] or row["resident_phone"] or f"user:{row['resident_id']}"
    print(
        f"RequestId={row['id']} | Resident={resident} | "
        f"KeyType={row['key_type']} | KeyValue={row['key_value']} | GateKeyId={row['gate_key_id']}"
    )

conn.close()
'@

$tempPy = [System.IO.Path]::GetTempFileName()
try {
    Set-Content -LiteralPath $tempPy -Value $pythonScript -Encoding UTF8
    $pythonArgs = @()
    if ($PythonVersion) {
        $pythonArgs += $PythonVersion
    }
    $pythonArgs += @($tempPy, $DatabaseUrl, $Needle, $projectRoot)
    & $PythonLauncher @pythonArgs
}
finally {
    if (Test-Path -LiteralPath $tempPy) {
        Remove-Item -LiteralPath $tempPy -Force
    }
}
