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
    -NginxExePath $NginxExePath `
    -NginxConfPath $NginxConfPath `
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
