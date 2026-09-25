[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$logRoot = Join-Path $resolvedRepoRoot 'logs\supervisor'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$supervisorLog = Join-Path $logRoot 'supervisor.log'
$mutex = [Threading.Mutex]::new($false, 'Local\SavoyaBackendSupervisor8000')
$ownsMutex = $false
try {
    $ownsMutex = $mutex.WaitOne(0)
    if (-not $ownsMutex) { exit 0 }
    while ($true) {
        try {
            $listener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($listener) {
                $backend = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
            } else {
                $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
                Remove-Item Env:ALLOWED_HOSTS_JSON,Env:CORS_ALLOW_ORIGINS_JSON -ErrorAction SilentlyContinue
                $env:PYTHONIOENCODING = 'utf-8'
                $backend = Start-Process -FilePath $PythonExe -WorkingDirectory $resolvedRepoRoot `
                    -ArgumentList @('-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000', '--no-access-log') `
                    -WindowStyle Hidden -PassThru `
                    -RedirectStandardOutput (Join-Path $logRoot "backend-$stamp.out.log") `
                    -RedirectStandardError (Join-Path $logRoot "backend-$stamp.err.log")
                "$(Get-Date -Format o) Started backend pid=$($backend.Id)" | Add-Content $supervisorLog
            }
            while (-not $backend.HasExited) { Start-Sleep -Seconds 5; $backend.Refresh() }
            "$(Get-Date -Format o) Backend exited; retrying in 10 seconds" | Add-Content $supervisorLog
        } catch {
            "$(Get-Date -Format o) Supervisor error: $($_.Exception.Message)" | Add-Content $supervisorLog
        }
        Start-Sleep -Seconds 10
    }
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
