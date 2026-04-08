Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Push-Location $ProjectRoot
try {
    py -3.12 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
