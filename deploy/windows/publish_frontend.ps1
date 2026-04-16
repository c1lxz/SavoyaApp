Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$FrontendRoot = Join-Path $ProjectRoot "frontend"

Push-Location $FrontendRoot
try {
    npm ci
    npx expo export --platform web --output-dir dist
    & (Join-Path $ProjectRoot "scripts\copy_latest_apk_to_dist.ps1") -RepoRoot $ProjectRoot
}
finally {
    Pop-Location
}
