[CmdletBinding()]
param([switch]$AllowWithoutPush)
$ErrorActionPreference = 'Stop'
function Invoke-BuildCommand {
    param([string]$Executable, [string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell turns native stderr into ErrorRecords when the
        # caller captures logs. Warnings are allowed; the exit code is decisive.
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($exitCode -ne 0) { throw "$Executable failed with exit code $exitCode" }
}
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
$originalStoreFile = $env:SAVOYA_RELEASE_STORE_FILE
$protectedStoreDirectory = $null
# Expo may recreate android/. Preserve a key located there before prebuild.
$resolvedStoreFile = (Resolve-Path -LiteralPath $originalStoreFile).Path
$androidDirectory = [IO.Path]::GetFullPath((Join-Path $frontendRoot 'android')) + [IO.Path]::DirectorySeparatorChar
if ($resolvedStoreFile.StartsWith($androidDirectory, [StringComparison]::OrdinalIgnoreCase)) {
    $protectedStoreDirectory = Join-Path ([IO.Path]::GetTempPath()) ('savoya-signing-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $protectedStoreDirectory | Out-Null
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $protectedStoreDirectory -AclObject $acl
    $env:SAVOYA_RELEASE_STORE_FILE = Join-Path $protectedStoreDirectory 'release.jks'
    Copy-Item -LiteralPath $resolvedStoreFile -Destination $env:SAVOYA_RELEASE_STORE_FILE
}
Push-Location $frontendRoot
try {
    Invoke-BuildCommand 'npm.cmd' @('ci', '--include=dev', '--no-audit', '--no-fund')
    Invoke-BuildCommand 'npm.cmd' @('run', 'typecheck')
    Invoke-BuildCommand 'npx.cmd' @('expo', 'prebuild', '--platform', 'android', '--no-install')
    Push-Location (Join-Path $frontendRoot 'android')
    try {
        Invoke-BuildCommand '.\gradlew.bat' @('assembleRelease', '--no-daemon', '--init-script', $releaseInputs, '-PreactNativeArchitectures=armeabi-v7a,arm64-v8a')
    } finally { Pop-Location }
    $appConfig = Get-Content (Join-Path $frontendRoot 'app.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $builtApk = Join-Path $frontendRoot 'android\app\build\outputs\apk\release\app-release.apk'
    if (-not (Test-Path -LiteralPath $builtApk)) { throw 'Signed APK not produced' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $apkArchive = [System.IO.Compression.ZipFile]::OpenRead($builtApk)
    try {
        & (Join-Path $PSScriptRoot 'assert_apk_native_libraries.ps1') -Archive $apkArchive
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
    $destination = Join-Path $repoRoot 'Экосистема Савоя.apk'
    Copy-Item -LiteralPath $builtApk -Destination $destination
    Get-FileHash -LiteralPath $destination -Algorithm SHA256
} finally {
    Pop-Location
    if ($protectedStoreDirectory -and -not (Test-Path -LiteralPath $resolvedStoreFile)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $resolvedStoreFile) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $protectedStoreDirectory 'release.jks') -Destination $resolvedStoreFile
    }
    $env:SAVOYA_RELEASE_STORE_FILE = $originalStoreFile
    if ($protectedStoreDirectory) {
        if ((Split-Path -Parent $protectedStoreDirectory) -ne [IO.Path]::GetTempPath().TrimEnd('\') -or
            (Split-Path -Leaf $protectedStoreDirectory) -notmatch '^savoya-signing-[a-f0-9]{32}$') {
            throw 'Unexpected signing directory; cleanup refused'
        }
        Remove-Item -LiteralPath $protectedStoreDirectory -Recurse -Force
    }
}
