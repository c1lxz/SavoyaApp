[CmdletBinding()]
param([switch]$AllowWithoutPush)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot 'frontend'
foreach ($settingName in @('SAVOYA_RELEASE_STORE_FILE', 'SAVOYA_RELEASE_STORE_PASSWORD', 'SAVOYA_RELEASE_KEY_ALIAS', 'SAVOYA_RELEASE_KEY_PASSWORD')) {
    if (-not [Environment]::GetEnvironmentVariable($settingName)) { throw "Missing environment setting: $settingName" }
}
if (-not (Test-Path -LiteralPath $env:SAVOYA_RELEASE_STORE_FILE -PathType Leaf)) { throw 'Signing keystore does not exist.' }
if (-not $AllowWithoutPush) { $env:SAVOYA_REQUIRE_PUSH = 'true' }
$env:EXPO_PUBLIC_USE_REAL_API = 'true'
$env:EXPO_PUBLIC_API_BASE_URL = 'https://ipksavoya.ru'
Push-Location $frontendRoot
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Typecheck failed' }
    & npx.cmd expo prebuild --platform android --no-install
    if ($LASTEXITCODE -ne 0) { throw 'Android prebuild failed' }
    Push-Location (Join-Path $frontendRoot 'android')
    try {
        & .\gradlew.bat assembleRelease --no-daemon '-PreactNativeArchitectures=armeabi-v7a,arm64-v8a'
        if ($LASTEXITCODE -ne 0) { throw 'Android release build failed' }
    } finally { Pop-Location }
    $appConfig = Get-Content (Join-Path $frontendRoot 'app.json') -Raw | ConvertFrom-Json
    $builtApk = Join-Path $frontendRoot 'android\app\build\outputs\apk\release\app-release.apk'
    if (-not (Test-Path -LiteralPath $builtApk)) { throw 'Signed APK not produced' }
    $destination = Join-Path $repoRoot ("Shlagbaum-Savoya-release-{0}.apk" -f $appConfig.expo.version)
    Copy-Item -LiteralPath $builtApk -Destination $destination
    Get-FileHash -LiteralPath $destination -Algorithm SHA256
} finally { Pop-Location }
