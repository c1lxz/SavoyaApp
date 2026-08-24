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
$versionMetadataPath = Join-Path $targetDirectory "shlagbaum-savoya.version.json"
$appConfigPath = Join-Path $resolvedRepoRoot "frontend\app.json"

if (-not (Test-Path -LiteralPath $appConfigPath -PathType Leaf)) {
    throw "Frontend app config not found: $appConfigPath"
}

$appConfig = Get-Content -LiteralPath $appConfigPath -Raw | ConvertFrom-Json
$expectedVersion = [string]$appConfig.expo.version
$expectedVersionCode = [int]$appConfig.expo.android.versionCode

if ([string]::IsNullOrWhiteSpace($expectedVersion) -or $expectedVersionCode -le 0) {
    throw "frontend/app.json must contain expo.version and a positive expo.android.versionCode"
}

$expectedNames = @(
    "Shlagbaum-Savoya-release-$expectedVersion.apk",
    "Savoya-release-$expectedVersion.apk"
)

$sourceApk = $expectedNames |
    ForEach-Object { Join-Path $resolvedRepoRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1

if (-not $sourceApk) {
    $availableNames = Get-ChildItem -LiteralPath $resolvedRepoRoot -Filter "*.apk" -File |
        Where-Object {
            $_.Name -like "Shlagbaum-Savoya-release-*.apk" -or $_.Name -like "Savoya-release-*.apk"
        } |
        Select-Object -ExpandProperty Name
    $availableDescription = if ($availableNames) { $availableNames -join ", " } else { "none" }
    throw (
        "APK for frontend version {0} (versionCode {1}) was not found. Expected one of: {2}. " +
        "Available release APKs: {3}. Refusing to publish a stale APK."
    ) -f $expectedVersion, $expectedVersionCode, ($expectedNames -join ", "), $availableDescription
}

New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
Copy-Item -LiteralPath $sourceApk -Destination $targetPath -Force

$sourceApkItem = Get-Item -LiteralPath $sourceApk
$apkHash = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash.ToLowerInvariant()
$versionMetadata = [ordered]@{
    version = $expectedVersion
    versionCode = $expectedVersionCode
    sourceFile = $sourceApkItem.Name
    sha256 = $apkHash
    sizeBytes = $sourceApkItem.Length
    publishedAtUtc = [DateTime]::UtcNow.ToString("o")
}
$versionMetadata |
    ConvertTo-Json |
    Set-Content -LiteralPath $versionMetadataPath -Encoding UTF8

Write-Host (
    "Published APK {0} (version {1}, versionCode {2}, SHA256 {3}) -> {4}" -f
    $sourceApkItem.Name,
    $expectedVersion,
    $expectedVersionCode,
    $apkHash,
    $targetPath
) -ForegroundColor Green
