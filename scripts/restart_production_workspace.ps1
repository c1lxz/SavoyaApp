[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$NginxExePath = "C:\nginx\nginx.exe",
    [string]$NginxConfPath = "C:\nginx\conf\nginx.conf",
    [string]$NginxServerName = "xn--80aaachc8cmu1au8c1f.xn--p1ai",
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [string]$BackendPythonLauncher = "py",
    [string]$BackendPythonVersion = "-3.12",
    [string]$GatePythonLauncher = "py",
    [string]$GatePythonVersion = "-3.12-32"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$startScript = Join-Path $resolvedRepoRoot "scripts\start_nginx_workspace.ps1"

if (-not (Test-Path -LiteralPath $startScript)) {
    throw "Production start script not found: $startScript"
}

function Select-FirstExistingPath {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if (-not $candidate) {
            continue
        }

        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return ""
}

function Get-RunningNginxPath {
    $process = Get-Process -Name "nginx" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path } |
        Select-Object -First 1

    if ($process) {
        return $process.Path
    }
    return ""
}

function Get-DownloadedNginxPath {
    $downloads = Join-Path $env:USERPROFILE "Downloads"
    if (-not (Test-Path -LiteralPath $downloads)) {
        return ""
    }

    $candidate = Get-ChildItem -LiteralPath $downloads -Directory -Filter "nginx-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        ForEach-Object {
            $path = Join-Path $_.FullName "nginx.exe"
            if (Test-Path -LiteralPath $path) {
                $path
            }
        } |
        Select-Object -First 1

    if ($candidate) {
        return $candidate
    }
    return ""
}

function Resolve-NginxPaths {
    $pathCommand = Get-Command nginx -ErrorAction SilentlyContinue
    $resolvedExe = Select-FirstExistingPath -Candidates @(
        $NginxExePath,
        (Get-RunningNginxPath),
        $(if ($pathCommand) { $pathCommand.Source }),
        (Get-DownloadedNginxPath),
        "C:\nginx\nginx.exe",
        "C:\Program Files\nginx\nginx.exe",
        "C:\Program Files (x86)\nginx\nginx.exe"
    )

    if (-not $resolvedExe) {
        throw "nginx.exe not found. Put nginx in PATH, keep it running once, or pass -NginxExePath."
    }

    $resolvedConf = Select-FirstExistingPath -Candidates @(
        $NginxConfPath,
        (Join-Path (Split-Path -Parent $resolvedExe) "conf\nginx.conf")
    )

    if (-not $resolvedConf) {
        throw "nginx.conf not found. Pass -NginxConfPath with the real nginx.conf path."
    }

    return [pscustomobject]@{
        Exe = $resolvedExe
        Conf = $resolvedConf
    }
}

function Stop-SavoyaProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Predicate
    )

    $currentProcessId = $PID
    $processes = Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $currentProcessId -and
            $_.CommandLine -and
            (& $Predicate $_.CommandLine)
        }

    foreach ($process in $processes) {
        Write-Host "Stopping $Description PID $($process.ProcessId)" -ForegroundColor Yellow
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Savoya production restart started." -ForegroundColor Green
Write-Host "Project: $resolvedRepoRoot"

$nginxPaths = Resolve-NginxPaths
Write-Host "nginx: $($nginxPaths.Exe)"
Write-Host "nginx config: $($nginxPaths.Conf)"

Stop-SavoyaProcess -Description "Savoya backend" -Predicate {
    param([string]$CommandLine)
    return $CommandLine -match "uvicorn" -and $CommandLine -match "backend\.app\.main:app"
}

Stop-SavoyaProcess -Description "Savoya frontend helper" -Predicate {
    param([string]$CommandLine)
    return $CommandLine -match "serve_frontend_prod\.py"
}

& $startScript `
    -RepoRoot $resolvedRepoRoot `
    -NginxExePath $nginxPaths.Exe `
    -NginxConfPath $nginxPaths.Conf `
    -NginxServerName $NginxServerName `
    -SkipPull `
    -BackendHost $BackendHost `
    -BackendPort $BackendPort `
    -BackendPythonLauncher $BackendPythonLauncher `
    -BackendPythonVersion $BackendPythonVersion `
    -FrontendUseRealApi $true `
    -FrontendApiBaseUrl "/api" `
    -GatePythonLauncher $GatePythonLauncher `
    -GatePythonVersion $GatePythonVersion

if ($LASTEXITCODE -ne 0) {
    throw "Savoya production start script failed with exit code $LASTEXITCODE"
}

Write-Host "Savoya production restart completed." -ForegroundColor Green
