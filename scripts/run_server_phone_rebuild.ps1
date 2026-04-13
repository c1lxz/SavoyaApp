[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Phone,
    [string]$ResidentName = "",
    [string]$PlotNumber = "",
    [switch]$Permanent,
    [string]$ExpiresAt = "",
    [string]$RepoRoot = "",
    [string]$PythonExe = "",
    [string]$PythonLauncher = $(if ($env:GATE_PYTHON_LAUNCHER) { $env:GATE_PYTHON_LAUNCHER } else { "py" }),
    [string]$PythonVersion = $(if ($env:GATE_PYTHON_VERSION) { $env:GATE_PYTHON_VERSION } else { "-3.12-32" }),
    [string]$MdbPath = "",
    [string]$SystemDbPath = "",
    [string[]]$GsmAccessPointId = @(),
    [switch]$PurgeExisting,
    [switch]$ClearContactPhone,
    [switch]$Apply,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"

function Import-DotEnvFile {
    param([string]$EnvFilePath)

    if (-not $EnvFilePath -or -not (Test-Path -LiteralPath $EnvFilePath)) {
        return
    }

    Get-Content -LiteralPath $EnvFilePath |
        Where-Object { $_ -match '^\s*[^#].*=.*$' } |
        ForEach-Object {
            $name, $value = $_ -split '=', 2
            $name = $name.Trim()
            $value = $value.Trim().Trim('"')
            if (-not (Test-Path "Env:$name")) {
                Set-Item -Path "Env:$name" -Value $value
            }
        }
}

function Resolve-RepoRoot {
    param([string]$Value)

    if ($Value) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Resolve-PythonCommand {
    param(
        [string]$ExplicitPythonExe,
        [string]$Launcher,
        [string]$Version,
        [string]$ResolvedRepoRoot
    )

    if ($ExplicitPythonExe) {
        if (-not (Test-Path -LiteralPath $ExplicitPythonExe)) {
            throw "Python executable not found: $ExplicitPythonExe"
        }
        return @{
            Executable = (Resolve-Path -LiteralPath $ExplicitPythonExe).Path
            PrefixArgs = @()
        }
    }

    $launcherCommand = Get-Command $Launcher -ErrorAction SilentlyContinue
    if ($launcherCommand) {
        return @{
            Executable = $launcherCommand.Source
            PrefixArgs = $(if ($Version) { @($Version) } else { @() })
        }
    }

    throw "Python was not found. Install 32-bit Python with pyodbc, or pass -PythonExe explicitly."
}

function Format-CommandPreview {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $parts = @($Executable)
    foreach ($argument in $Arguments) {
        if ($argument -match '\s') {
            $parts += '"' + $argument.Replace('"', '\"') + '"'
        }
        else {
            $parts += $argument
        }
    }
    return ($parts -join ' ')
}

$resolvedRepoRoot = Resolve-RepoRoot -Value $RepoRoot
if (-not (Test-Path -LiteralPath $resolvedRepoRoot)) {
    throw "RepoRoot not found: $resolvedRepoRoot"
}

Import-DotEnvFile -EnvFilePath (Join-Path $resolvedRepoRoot ".env")

if (-not $MdbPath) {
    $MdbPath = $env:GATE_MDB_PATH
}
if (-not $SystemDbPath) {
    $SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH })
}

$rebuildScript = Join-Path $resolvedRepoRoot "scripts\rebuild_gate_phone_pass.py"
if (-not (Test-Path -LiteralPath $rebuildScript)) {
    throw "Rebuild script not found: $rebuildScript"
}

$pythonCommand = Resolve-PythonCommand `
    -ExplicitPythonExe $PythonExe `
    -Launcher $PythonLauncher `
    -Version $PythonVersion `
    -ResolvedRepoRoot $resolvedRepoRoot

$commandArgs = @()
$commandArgs += $pythonCommand.PrefixArgs
$commandArgs += @($rebuildScript, $Phone)
if ($ResidentName) {
    $commandArgs += @("--resident-name", $ResidentName)
}
if ($PlotNumber) {
    $commandArgs += @("--plot-number", $PlotNumber)
}
if ($Permanent) {
    $commandArgs += "--permanent"
}
elseif ($ExpiresAt) {
    $commandArgs += @("--expires-at", $ExpiresAt)
}
if ($MdbPath) {
    $commandArgs += @("--mdb", $MdbPath)
}
if ($SystemDbPath) {
    $commandArgs += @("--systemdb", $SystemDbPath)
}
foreach ($pointId in ($GsmAccessPointId | Select-Object -Unique)) {
    foreach ($rawValue in ($pointId -split ',')) {
        $trimmed = $rawValue.Trim()
        if (-not $trimmed) {
            continue
        }
        $commandArgs += @("--gsm-access-point-id", ([int]$trimmed).ToString())
    }
}
if ($PurgeExisting) {
    $commandArgs += "--purge-existing"
}
if ($ClearContactPhone) {
    $commandArgs += "--clear-contact-phone"
}
if ($Apply) {
    $commandArgs += "--apply"
}

$commandPreview = Format-CommandPreview -Executable $pythonCommand.Executable -Arguments $commandArgs
Write-Host "RepoRoot: $resolvedRepoRoot"
Write-Host "Command: $commandPreview"

if ($Preview) {
    return
}

$previousPythonPath = $env:PYTHONPATH
if ($previousPythonPath) {
    $env:PYTHONPATH = "$resolvedRepoRoot;$previousPythonPath"
}
else {
    $env:PYTHONPATH = $resolvedRepoRoot
}

Push-Location -LiteralPath $resolvedRepoRoot
try {
    & $pythonCommand.Executable @commandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Rebuild command failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $previousPythonPath
    }
}
