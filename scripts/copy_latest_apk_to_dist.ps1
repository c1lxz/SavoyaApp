[CmdletBinding()]
param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) {
    if ($PSScriptRoot) {
        $RepoRoot = Split-Path -Parent $PSScriptRoot
    }
    else {
        $RepoRoot = (Get-Location).Path
    }
}

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$targetDirectory = Join-Path $resolvedRepoRoot "frontend\dist\download"
$targetPath = Join-Path $targetDirectory "shlagbaum-savoya.apk"

$sourceApk = Get-ChildItem -LiteralPath $resolvedRepoRoot -Filter "*.apk" -File |
    Where-Object {
        $_.Name -like "Shlagbaum-Savoya-release-*.apk" -or $_.Name -like "Savoya-release-*.apk"
    } |
    Sort-Object LastWriteTimeUtc, Name -Descending |
    Select-Object -First 1

if (-not $sourceApk) {
    throw "APK file not found in $resolvedRepoRoot"
}

New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
Copy-Item -LiteralPath $sourceApk.FullName -Destination $targetPath -Force

Write-Host ("Copied APK to download bundle: {0} -> {1}" -f $sourceApk.Name, $targetPath) -ForegroundColor Green
