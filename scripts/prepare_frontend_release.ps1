[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [bool]$UseRealApi = $true,
    [string]$ApiBaseUrl = '/api',
    [switch]$Bootstrap,
    [switch]$Preview
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Invoke-FrontendCommand {
    param([string]$Executable, [string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($exitCode -ne 0) { throw "$Executable failed with exit code $exitCode; live frontend was preserved" }
}
$frontend = Join-Path (Resolve-Path -LiteralPath $RepoRoot).Path 'frontend'
$lock = Join-Path $frontend 'package-lock.json'
$modules = Join-Path $frontend 'node_modules'
$stamp = Join-Path $modules '.savoya-package-lock.sha256'
$dist = Join-Path $frontend 'dist'
if ($Preview) {
    Write-Host '[preview] refresh dependencies when the lock changes; build outside live dist; publish index last'
    return
}
if (-not (Test-Path -LiteralPath $lock -PathType Leaf)) { throw 'package-lock.json is required' }
$fingerprint = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash
$installedFingerprint = if (Test-Path -LiteralPath $stamp) { (Get-Content -LiteralPath $stamp -Raw).Trim() } else { '' }
$build = Join-Path $frontend ('.savoya-web-' + [Guid]::NewGuid().ToString('N'))
$previousRealApi = $env:EXPO_PUBLIC_USE_REAL_API
$previousApi = $env:EXPO_PUBLIC_API_BASE_URL
Push-Location -LiteralPath $frontend
try {
    if ($Bootstrap -or -not (Test-Path -LiteralPath $modules) -or $installedFingerprint -ne $fingerprint) {
        Invoke-FrontendCommand 'npm.cmd' @('ci', '--include=dev', '--no-audit', '--no-fund')
        [IO.File]::WriteAllText($stamp, $fingerprint)
    }
    $env:EXPO_PUBLIC_USE_REAL_API = $UseRealApi.ToString().ToLowerInvariant()
    $env:EXPO_PUBLIC_API_BASE_URL = $ApiBaseUrl
    Invoke-FrontendCommand 'npx.cmd' @('expo', 'export', '--platform', 'web', '--output-dir', $build)
    $index = Join-Path $build 'index.html'
    if (-not (Test-Path -LiteralPath $index -PathType Leaf)) { throw 'Frontend export did not produce index.html; live frontend was preserved' }
    New-Item -ItemType Directory -Path $dist -Force | Out-Null
    # Keep existing hashed assets and downloads for clients using the previous index.
    Get-ChildItem -LiteralPath $build -Force | Where-Object Name -ne 'index.html' |
        Copy-Item -Destination $dist -Recurse -Force
    $pendingIndex = Join-Path $dist 'index.html.pending'
    Copy-Item -LiteralPath $index -Destination $pendingIndex -Force
    $liveIndex = Join-Path $dist 'index.html'
    if (Test-Path -LiteralPath $liveIndex) { [IO.File]::Replace($pendingIndex, $liveIndex, (Join-Path $dist 'index.html.previous')) }
    else { [IO.File]::Move($pendingIndex, $liveIndex) }
    # An Android release is independent of web startup. Keep its current metadata
    # if no matching, verified APK is available rather than relabeling old bytes.
    try { & (Join-Path $PSScriptRoot 'copy_latest_apk_to_dist.ps1') -RepoRoot $RepoRoot }
    catch { Write-Warning "Web published; existing Android download retained. $($_.Exception.Message)" }
}
finally {
    $env:EXPO_PUBLIC_USE_REAL_API = $previousRealApi
    $env:EXPO_PUBLIC_API_BASE_URL = $previousApi
    Pop-Location
    # Only delete the temporary directory created by this invocation.
    if ((Split-Path -Parent $build) -ne $frontend -or (Split-Path -Leaf $build) -notmatch '^\.savoya-web-[a-f0-9]{32}$') {
        throw 'Unexpected build directory; cleanup refused'
    }
    if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build -Recurse -Force }
}
