$ErrorActionPreference = "Stop"

$sshPort = 2222
$publicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIl6xMWdmEpefEERu7vFFRtW8o58xuoZtgcGQP/MZMEh codex-savoya-production-2026-08-20"
$expectedHash = "23f50f3458c4c5d0b12217c6a5ddfde0137210a30fa870e98b29827f7b43aba5"
$installDirectory = "C:\Program Files\OpenSSH"
$sshDirectory = "C:\ProgramData\ssh"
$configPath = Join-Path $sshDirectory "sshd_config"
$adminKeysPath = Join-Path $sshDirectory "administrators_authorized_keys"
$archivePath = Join-Path $PSScriptRoot "OpenSSH-Win64.zip"

$isAdmin = ([Security.Principal.WindowsPrincipal] (
    [Security.Principal.WindowsIdentity]::GetCurrent()
)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "Run this script from an elevated PowerShell window"
}

$actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) {
    throw "OpenSSH archive SHA256 mismatch: $actualHash"
}

if (Test-Path -LiteralPath $installDirectory) {
    if (-not (Test-Path -LiteralPath (Join-Path $installDirectory "sshd.exe"))) {
        throw "OpenSSH install directory already exists but does not contain sshd.exe"
    }
} else {
    $extractDirectory = Join-Path $env:TEMP ("savoya-openssh-extract-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $extractDirectory -Force | Out-Null
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDirectory
    $sourceDirectory = Join-Path $extractDirectory "OpenSSH-Win64"
    New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
    Copy-Item -Path (Join-Path $sourceDirectory "*") -Destination $installDirectory -Recurse
}

if (-not (Get-Service -Name sshd -ErrorAction SilentlyContinue)) {
    & powershell.exe `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File (Join-Path $installDirectory "install-sshd.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "install-sshd.ps1 failed with exit code $LASTEXITCODE"
    }
}

New-Item -ItemType Directory -Path $sshDirectory -Force | Out-Null

@"
Port $sshPort
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthorizedKeysFile .ssh/authorized_keys

Match Group administrators
    AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys
"@ | Set-Content -LiteralPath $configPath -Encoding Ascii

$publicKey | Set-Content -LiteralPath $adminKeysPath -Encoding Ascii
icacls $adminKeysPath /inheritance:r | Out-Null
icacls $adminKeysPath /grant "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null

& (Join-Path $installDirectory "ssh-keygen.exe") -A
& (Join-Path $installDirectory "sshd.exe") -t
if ($LASTEXITCODE -ne 0) {
    throw "sshd_config validation failed"
}

$ruleName = "Savoya temporary SSH 2222"
$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Set-NetFirewallRule -DisplayName $ruleName -Enabled True -Direction Inbound -Action Allow -Profile Any
} else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $sshPort `
        -Profile Any | Out-Null
}

Set-Service sshd -StartupType Automatic
Start-Service sshd -ErrorAction SilentlyContinue
Restart-Service sshd

Write-Host ""
Write-Host "=== SSH READY ===" -ForegroundColor Green
Write-Host "User: $env:USERNAME"
Write-Host "Computer: $env:COMPUTERNAME"
Get-NetTCPConnection -State Listen -LocalPort $sshPort |
    Select-Object LocalAddress, LocalPort, OwningProcess
