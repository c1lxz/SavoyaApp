[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\User\Desktop\SavoyaApp\SavoyaApp",
    [string[]]$Phone = @("89111253128", "89522379185"),
    [string]$PythonExe = "",
    [string]$PythonLauncher = $(if ($env:GATE_PYTHON_LAUNCHER) { $env:GATE_PYTHON_LAUNCHER } else { "py" }),
    [string]$PythonVersion = $(if ($env:GATE_PYTHON_VERSION) { $env:GATE_PYTHON_VERSION } else { "-3.12-32" }),
    [string]$MdbPath = "",
    [string]$SystemDbPath = "",
    [int[]]$GsmAccessPointId = @(),
    [switch]$ClearContactPhone,
    [switch]$PurgeAll,
    [switch]$Apply,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"

function Import-DotEnvFile {
    param([Parameter(Mandatory = $true)][string]$EnvFilePath)

    if (-not (Test-Path -LiteralPath $EnvFilePath)) {
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
    param([Parameter(Mandatory = $true)][string]$Value)

    if (-not $Value) {
        throw "RepoRoot is empty."
    }
    return [System.IO.Path]::GetFullPath($Value)
}

function Get-GsmAccessPointIds {
    param([int[]]$ExplicitIds)

    if ($ExplicitIds.Count -gt 0) {
        return @($ExplicitIds | Select-Object -Unique)
    }

    if ($env:GSM_ACCESS_POINT_IDS_JSON) {
        try {
            $parsed = ConvertFrom-Json -InputObject $env:GSM_ACCESS_POINT_IDS_JSON
            $resolved = @(
                $parsed |
                    ForEach-Object { [int]$_ } |
                    Select-Object -Unique
            )
            if ($resolved.Count -gt 0) {
                return $resolved
            }
        }
        catch {
        }
    }

    return @(5, 6)
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

    $candidatePaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312-32\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311-32\python.exe"),
        "C:\Python312-32\python.exe",
        "C:\Python311-32\python.exe",
        (Join-Path $ResolvedRepoRoot ".venv\Scripts\python.exe")
    )

    foreach ($candidate in $candidatePaths) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return @{
                Executable = $candidate
                PrefixArgs = @()
            }
        }
    }

    throw "Python was not found. Install 32-bit Python with pyodbc, or pass -PythonExe explicitly."
}

function Test-PythonRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$PrefixArgs
    )

    $probeArgs = @()
    $probeArgs += $PrefixArgs
    $probeArgs += @(
        "-c",
        "import struct, pyodbc; print(struct.calcsize('P') * 8); print(pyodbc.version)"
    )
    $output = & $Executable @probeArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python runtime check failed. Ensure pyodbc is installed. Output: $($output -join [Environment]::NewLine)"
    }
    return @($output)
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

$envFile = Join-Path $resolvedRepoRoot ".env"
Import-DotEnvFile -EnvFilePath $envFile

if (-not $MdbPath) {
    $MdbPath = $env:GATE_MDB_PATH
}
if (-not $SystemDbPath) {
    $SystemDbPath = $(if ($env:GATE_SYSTEMDB_PATH) { $env:GATE_SYSTEMDB_PATH } else { $env:GATE_MDW_PATH })
}

if (-not $MdbPath) {
    throw "GATE_MDB_PATH is not set."
}
if (-not $SystemDbPath) {
    throw "GATE_SYSTEMDB_PATH is not set."
}

$cleanupScript = Join-Path $resolvedRepoRoot "scripts\cleanup_gate_phone_duplicates.py"
if (-not (Test-Path -LiteralPath $cleanupScript)) {
    throw "Cleanup script not found: $cleanupScript"
}

$resolvedGsmIds = Get-GsmAccessPointIds -ExplicitIds $GsmAccessPointId
$pythonCommand = Resolve-PythonCommand `
    -ExplicitPythonExe $PythonExe `
    -Launcher $PythonLauncher `
    -Version $PythonVersion `
    -ResolvedRepoRoot $resolvedRepoRoot
$pythonProbe = Test-PythonRuntime -Executable $pythonCommand.Executable -PrefixArgs $pythonCommand.PrefixArgs

$commandArgs = @()
$commandArgs += $pythonCommand.PrefixArgs
$commandArgs += @($cleanupScript)
$commandArgs += @($Phone | Where-Object { $_ })
$commandArgs += @("--mdb", $MdbPath, "--systemdb", $SystemDbPath)
foreach ($pointId in $resolvedGsmIds) {
    $commandArgs += @("--gsm-access-point-id", $pointId.ToString())
}
if ($ClearContactPhone) {
    $commandArgs += "--clear-contact-phone"
}
if ($PurgeAll) {
    $commandArgs += "--purge-all"
}
if ($Apply) {
    $commandArgs += "--apply"
}

Write-Host "RepoRoot: $resolvedRepoRoot"
Write-Host "MDB: $MdbPath"
Write-Host "SystemDB: $SystemDbPath"
Write-Host "Phones: $($Phone -join ', ')"
Write-Host "GSM readers: $($resolvedGsmIds -join ', ')"
Write-Host "Python: $($pythonCommand.Executable)"
if ($pythonProbe.Count -ge 2) {
    Write-Host "Python probe: $($pythonProbe[0])-bit, pyodbc $($pythonProbe[1])"
}
Write-Host "Mode: $(if ($Apply) { 'APPLY' } else { 'DRY-RUN' })$(if ($PurgeAll) { ' + PURGE-ALL' } else { '' })"

$commandPreview = Format-CommandPreview -Executable $pythonCommand.Executable -Arguments $commandArgs
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
        throw "Cleanup command failed with exit code $LASTEXITCODE"
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
