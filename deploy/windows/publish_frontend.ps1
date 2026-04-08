Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$FrontendRoot = Join-Path $ProjectRoot "frontend"

Push-Location $FrontendRoot
try {
    npm ci
    npx expo export --platform web --output-dir dist
}
finally {
    Pop-Location
}
