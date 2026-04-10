Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Push-Location $ProjectRoot
try {
    # Let backend settings come from the project .env instead of any stale
    # shell-scoped overrides left by dev workspace helpers.
    Remove-Item Env:ALLOWED_HOSTS_JSON -ErrorAction SilentlyContinue
    Remove-Item Env:CORS_ALLOW_ORIGINS_JSON -ErrorAction SilentlyContinue
    py -3.12 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
