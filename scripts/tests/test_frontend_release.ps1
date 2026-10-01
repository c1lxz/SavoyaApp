$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem
$scripts = Split-Path -Parent $PSScriptRoot
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('savoya-launcher-test-' + [Guid]::NewGuid().ToString('N'))
$originalPath = $env:PATH
$originalApi = $env:EXPO_PUBLIC_API_BASE_URL
$originalRealApi = $env:EXPO_PUBLIC_USE_REAL_API
$checks = 0
function Assert($condition, $message) {
    if (-not $condition) { throw $message }
    $script:checks++
}
function Expect-Failure($action, $message) {
    $failed = $false
    try { & $action } catch { $failed = $true }
    Assert $failed $message
}
function Make-Apk($config) {
    $path = Join-Path $fixture 'Savoya-release-1.6.2.apk'
    if (Test-Path $path) { Remove-Item -LiteralPath $path }
    $archive = [IO.Compression.ZipFile]::Open($path, 'Create')
    try {
        $writer = [IO.StreamWriter]::new($archive.CreateEntry('assets/app.config').Open())
        try { $writer.Write(($config | ConvertTo-Json -Depth 8)) } finally { $writer.Dispose() }
        foreach($library in @('libexpo-av.so','libexpo-modules-core.so','libhermes.so','libreactnativejni.so')){
            $stream=$archive.CreateEntry("lib/arm64-v8a/$library").Open()
            try{$stream.WriteByte(1)}finally{$stream.Dispose()}
        }
    } finally { $archive.Dispose() }
}
try {
    New-Item -ItemType Directory -Path "$fixture\bin", "$fixture\frontend\node_modules", "$fixture\frontend\dist\download" -Force | Out-Null
    $app = @{name='Test Savoya';version='1.6.2';android=@{package='com.savoya.app';versionCode=19}}
    @{expo=$app} | ConvertTo-Json -Depth 8 | Set-Content "$fixture\frontend\app.json" -Encoding UTF8
    '{}' | Set-Content "$fixture\frontend\package-lock.json"
    'old index' | Set-Content "$fixture\frontend\dist\index.html"
    'old asset' | Set-Content "$fixture\frontend\dist\old.js"
    'previous apk' | Set-Content "$fixture\frontend\dist\download\shlagbaum-savoya.apk"
    'previous metadata' | Set-Content "$fixture\frontend\dist\download\shlagbaum-savoya.version.json"
    $env:SAVOYA_TEST_CALLS = "$fixture\npm-calls.txt"
    $env:SAVOYA_TEST_NPM = "$fixture\fake-npm.ps1"
    $env:SAVOYA_TEST_NPX = "$fixture\fake-export.ps1"
    @'
$ErrorActionPreference='Stop'
'ci' | Add-Content $env:SAVOYA_TEST_CALLS
if ($env:SAVOYA_TEST_INSTALL_WARNING -eq '1') { [Console]::Error.WriteLine('npm warning fixture') }
if ($env:SAVOYA_TEST_INSTALL_FAIL -eq '1') { exit 1 }
New-Item -ItemType Directory -Path node_modules -Force | Out-Null
exit 0
'@ | Set-Content $env:SAVOYA_TEST_NPM -Encoding UTF8
    @'
$ErrorActionPreference='Stop'
$outputIndex=[Array]::IndexOf($args,'--output-dir')+1
$output=$args[$outputIndex]
New-Item -ItemType Directory -Path $output -Force | Out-Null
'new asset' | Set-Content "$output\new.js"
if ($env:SAVOYA_TEST_BUILD_FAIL -eq '1') { exit 1 }
if ($env:SAVOYA_TEST_BUILD_FAIL -ne 'noindex') { '<script src="new.js"></script>' | Set-Content "$output\index.html" }
exit 0
'@ | Set-Content $env:SAVOYA_TEST_NPX -Encoding UTF8
    "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%SAVOYA_TEST_NPM%`" %*`r`nexit /b %errorlevel%" | Set-Content "$fixture\bin\npm.cmd" -Encoding ASCII
    "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%SAVOYA_TEST_NPX%`" %*`r`nexit /b %errorlevel%" | Set-Content "$fixture\bin\npx.cmd" -Encoding ASCII
    $env:PATH = "$fixture\bin;$originalPath"
    $env:EXPO_PUBLIC_API_BASE_URL = 'original-api'
    $env:EXPO_PUBLIC_USE_REAL_API = 'false'
    $prepare = { & "$scripts\prepare_frontend_release.ps1" -RepoRoot $fixture }
    $env:SAVOYA_TEST_BUILD_FAIL = '1'
    Expect-Failure $prepare 'Failed export must fail the preparation'
    Assert ((Get-Content "$fixture\frontend\dist\index.html" -Raw).Trim() -eq 'old index') 'Failed export changed live index'
    Assert ((Get-Content "$fixture\frontend\dist\old.js" -Raw).Trim() -eq 'old asset') 'Failed export lost previous assets'
    Assert ($env:EXPO_PUBLIC_API_BASE_URL -eq 'original-api' -and $env:EXPO_PUBLIC_USE_REAL_API -eq 'false') 'Environment was not restored after failure'
    Assert (@(Get-ChildItem "$fixture\frontend" -Directory -Filter '.savoya-web-*').Count -eq 0) 'Temporary export leaked'
    $env:SAVOYA_TEST_BUILD_FAIL = 'noindex'
    Expect-Failure $prepare 'Export without index must be rejected'
    $env:SAVOYA_TEST_BUILD_FAIL = ''
    & $prepare
    Assert ((Get-Content "$fixture\frontend\dist\index.html" -Raw).Contains('new.js')) 'Successful export was not published'
    Assert (Test-Path "$fixture\frontend\dist\new.js") 'Published index has no matching asset'
    Assert (Test-Path "$fixture\frontend\dist\old.js") 'Previous clients lost hashed assets'
    Assert ((Get-Content "$fixture\frontend\dist\download\shlagbaum-savoya.version.json" -Raw).Trim() -eq 'previous metadata') 'Missing APK changed download metadata'
    Assert (@(Get-Content $env:SAVOYA_TEST_CALLS).Count -eq 1) 'Unchanged lock reinstalled dependencies'
    '{"changed":true}' | Set-Content "$fixture\frontend\package-lock.json"
    $env:SAVOYA_TEST_INSTALL_FAIL = '1'
    $before = (Get-FileHash "$fixture\frontend\dist\index.html").Hash
    Expect-Failure $prepare 'Failed dependency refresh must reject release'
    Assert ((Get-FileHash "$fixture\frontend\dist\index.html").Hash -eq $before) 'Dependency failure modified working frontend'
    $env:SAVOYA_TEST_INSTALL_FAIL = ''
    $env:SAVOYA_TEST_INSTALL_WARNING = '1'
    & $prepare *> "$fixture\captured-launcher.log"
    Assert (@(Get-Content $env:SAVOYA_TEST_CALLS).Count -eq 3) 'Changed lock did not retry installation'
    Assert ((Get-Content "$fixture\captured-launcher.log" -Raw).Contains('npm warning fixture')) 'Captured native warning was lost'
    $stale = @{name='Test Savoya';version='1.6.1';android=@{package='com.savoya.app';versionCode=18}}
    Make-Apk $stale
    Expect-Failure { & "$scripts\copy_latest_apk_to_dist.ps1" -RepoRoot $fixture } 'Renamed stale APK was published'
    Assert ((Get-Content "$fixture\frontend\dist\download\shlagbaum-savoya.version.json" -Raw).Trim() -eq 'previous metadata') 'Rejected APK corrupted download metadata'
    Make-Apk $app
    $incomplete=[IO.Compression.ZipFile]::Open("$fixture\Savoya-release-1.6.2.apk",'Update')
    try {
        $stream=$incomplete.CreateEntry('lib/x86_64/libhermes.so').Open()
        try{$stream.WriteByte(1)}finally{$stream.Dispose()}
    } finally{$incomplete.Dispose()}
    Expect-Failure { & "$scripts\copy_latest_apk_to_dist.ps1" -RepoRoot $fixture } 'APK with a partially packaged architecture was published'
    Assert ((Get-Content "$fixture\frontend\dist\download\shlagbaum-savoya.version.json" -Raw).Trim() -eq 'previous metadata') 'Native ABI rejection corrupted download metadata'
    Make-Apk $app
    $incomplete=[IO.Compression.ZipFile]::Open("$fixture\Savoya-release-1.6.2.apk",'Update')
    try{$incomplete.GetEntry('lib/arm64-v8a/libexpo-av.so').Delete()}finally{$incomplete.Dispose()}
    Expect-Failure { & "$scripts\copy_latest_apk_to_dist.ps1" -RepoRoot $fixture } 'APK missing its media runtime was published'
    Make-Apk $app
    & "$scripts\copy_latest_apk_to_dist.ps1" -RepoRoot $fixture
    $metadata = Get-Content "$fixture\frontend\dist\download\shlagbaum-savoya.version.json" -Raw | ConvertFrom-Json
    Assert ($metadata.versionCode -eq 19 -and $metadata.version -eq '1.6.2') 'Release metadata has wrong version'
    Assert ($metadata.sha256 -eq (Get-FileHash "$fixture\frontend\dist\download\shlagbaum-savoya.apk").Hash.ToLowerInvariant()) 'Download differs from release hash'
    Write-Output "Launcher/download recovery: $checks checks passed"
} finally {
    $env:PATH = $originalPath
    $env:EXPO_PUBLIC_API_BASE_URL = $originalApi
    $env:EXPO_PUBLIC_USE_REAL_API = $originalRealApi
    foreach ($name in @('SAVOYA_TEST_CALLS','SAVOYA_TEST_NPM','SAVOYA_TEST_NPX','SAVOYA_TEST_INSTALL_FAIL','SAVOYA_TEST_BUILD_FAIL','SAVOYA_TEST_INSTALL_WARNING')) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    if ((Split-Path -Parent $fixture) -ne [IO.Path]::GetTempPath().TrimEnd('\') -or (Split-Path -Leaf $fixture) -notmatch '^savoya-launcher-test-[a-f0-9]{32}$') { throw 'Unexpected test directory; cleanup refused' }
    Remove-Item -LiteralPath $fixture -Recurse -Force
}
