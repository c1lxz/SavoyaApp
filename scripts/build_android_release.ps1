[CmdletBinding()]
param([switch]$AllowWithoutPush)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot 'frontend'
foreach ($settingName in @('SAVOYA_RELEASE_STORE_FILE', 'SAVOYA_RELEASE_STORE_PASSWORD', 'SAVOYA_RELEASE_KEY_ALIAS', 'SAVOYA_RELEASE_KEY_PASSWORD')) {
    if (-not [Environment]::GetEnvironmentVariable($settingName)) { throw "Missing environment setting: $settingName" }
}
if (-not (Test-Path -LiteralPath $env:SAVOYA_RELEASE_STORE_FILE -PathType Leaf)) { throw 'Signing keystore does not exist.' }
$env:SAVOYA_BUILD_VARIANT = 'production'
$env:SAVOYA_REQUIRE_PUSH = if ($AllowWithoutPush) { 'false' } else { 'true' }
$env:EXPO_PUBLIC_USE_REAL_API = 'true'
$env:EXPO_PUBLIC_API_BASE_URL = 'https://ipksavoya.ru'
$env:EXPO_PUBLIC_SITE_ORIGIN = 'https://ipksavoya.ru'
$env:NODE_ENV = 'production'
$env:EXPO_NO_DOTENV = '1'
$releaseInputs = Join-Path $PSScriptRoot 'android-release-inputs.gradle'
Push-Location $frontendRoot
try {
    & npm.cmd ci --include=dev --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Typecheck failed' }
    & npx.cmd expo prebuild --platform android --no-install
    if ($LASTEXITCODE -ne 0) { throw 'Android prebuild failed' }
    Push-Location (Join-Path $frontendRoot 'android')
    try {
        & .\gradlew.bat assembleRelease --no-daemon --init-script $releaseInputs '-PreactNativeArchitectures=armeabi-v7a,arm64-v8a'
        if ($LASTEXITCODE -ne 0) { throw 'Android release build failed' }
    } finally { Pop-Location }
    $appConfig = Get-Content (Join-Path $frontendRoot 'app.json') -Raw | ConvertFrom-Json
    $builtApk = Join-Path $frontendRoot 'android\app\build\outputs\apk\release\app-release.apk'
    if (-not (Test-Path -LiteralPath $builtApk)) { throw 'Signed APK not produced' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $apkArchive = [System.IO.Compression.ZipFile]::OpenRead($builtApk)
    try {
        $configEntry = $apkArchive.GetEntry('assets/app.config')
        $bundleEntry = $apkArchive.GetEntry('assets/index.android.bundle')
        if (-not $configEntry -or -not $bundleEntry) { throw 'APK is missing its runtime config or JS bundle.' }
        $configReader = [System.IO.StreamReader]::new($configEntry.Open())
        try { $embeddedConfig = $configReader.ReadToEnd() | ConvertFrom-Json } finally { $configReader.Dispose() }
        if ($embeddedConfig.android.package -ne 'com.savoya.app' -or
            $embeddedConfig.version -ne $appConfig.expo.version -or
            $embeddedConfig.android.versionCode -ne $appConfig.expo.android.versionCode) {
            throw 'APK contains stale or non-production app configuration.'
        }
        if (-not $AllowWithoutPush -and $embeddedConfig.extra.newsPushConfigured -ne $true) {
            throw 'APK contains a stale configuration with Firebase disabled.'
        }
        $bundleReader = [System.IO.StreamReader]::new($bundleEntry.Open())
        try { $embeddedBundle = $bundleReader.ReadToEnd() } finally { $bundleReader.Dispose() }
        # The URL's presence alone is insufficient: it also exists as a fallback.
        # Environment inputs above force a fresh bundle; reject any loopback URL too.
        if (-not $embeddedBundle.Contains('https://ipksavoya.ru') -or
            $embeddedBundle -match 'https?://(?:127(?:\.[0-9]{1,3}){3}|localhost|\[::1\]|10\.0\.2\.2)') {
            throw 'APK does not contain the production API configuration.'
        }
    } finally { $apkArchive.Dispose() }
    $destination = Join-Path $repoRoot ("Shlagbaum-Savoya-release-{0}.apk" -f $appConfig.expo.version)
    Copy-Item -LiteralPath $builtApk -Destination $destination
    Get-FileHash -LiteralPath $destination -Algorithm SHA256
} finally { Pop-Location }
