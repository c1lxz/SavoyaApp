[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$NginxExePath = "C:\nginx\nginx.exe",
    [string]$NginxConfPath = "C:\nginx\conf\nginx.conf",
    [string]$NginxServerName = "ipksavoya.ru",
    [switch]$SkipPull,
    [switch]$Bootstrap,
    [switch]$OpenToolShell,
    [switch]$Preview,
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [string]$BackendPythonLauncher = "py",
    [string]$BackendPythonVersion = "-3.12",
    [bool]$FrontendUseRealApi = $true,
    [string]$FrontendApiBaseUrl = "/api",
    [string]$GatePythonLauncher = "py",
    [string]$GatePythonVersion = "-3.12-32"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $RepoRoot) {
    if ($PSScriptRoot) {
        $RepoRoot = Split-Path -Parent $PSScriptRoot
    }
    else {
        $RepoRoot = (Get-Location).Path
    }
}

function Quote-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)

    return "'" + $Value.Replace("'", "''") + "'"
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

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $commandPreview = Format-CommandPreview -Executable $Executable -Arguments $Arguments
    if ($Preview) {
        Write-Host "[preview] $Description"
        Write-Host "  $commandPreview"
        return
    }

    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Description failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-ExternalCommandResult {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $commandPreview = Format-CommandPreview -Executable $Executable -Arguments $Arguments
    if ($Preview) {
        Write-Host "[preview] $Description"
        Write-Host "  $commandPreview"
        return [pscustomobject]@{
            ExitCode = 0
            Output = ""
        }
    }

    Push-Location -LiteralPath $WorkingDirectory
    try {
        $output = & $Executable @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($output) {
        $output | ForEach-Object { Write-Host $_ }
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = ($output | Out-String).Trim()
    }
}

function New-PowerShellWindowCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$Body
    )

    $parts = @(
        "`$Host.UI.RawUI.WindowTitle = $(Quote-PowerShellLiteral -Value $Title)",
        "Set-Location -LiteralPath $(Quote-PowerShellLiteral -Value $WorkingDirectory)"
    ) + $Body

    return ($parts -join "; ")
}

function Start-WorkspaceWindow {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$Body
    )

    $command = New-PowerShellWindowCommand -Title $Title -WorkingDirectory $WorkingDirectory -Body $Body
    if ($Preview) {
        Write-Host "[preview] open $Title"
        Write-Host "  powershell.exe -NoExit -ExecutionPolicy Bypass -EncodedCommand <base64>"
        Write-Host "  command: $command"
        return
    }

    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    Start-Process -FilePath "powershell.exe" `
        -WorkingDirectory $WorkingDirectory `
        -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encodedCommand) | Out-Null
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

function Invoke-CurlRequest {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $curl = Get-Command "curl.exe" -ErrorAction SilentlyContinue
    if (-not $curl) {
        throw "curl.exe is required for nginx verification"
    }

    $output = & $curl.Source @Arguments 2>&1
    $exitCode = $LASTEXITCODE

    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "curl.exe failed with exit code $exitCode`n$output"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = ($output | Out-String).Trim()
    }
}

function Get-NginxProcessesForExecutable {
    param([Parameter(Mandatory = $true)][string]$ExecutablePath)

    $resolvedExecutablePath = (Resolve-Path -LiteralPath $ExecutablePath).Path
    return @(Get-CimInstance Win32_Process -Filter "name = 'nginx.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath -ieq $resolvedExecutablePath })
}

function Wait-ForNginxProcessesToExit {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [int]$TimeoutSeconds = 10
    )

    if ($Preview) {
        return $true
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-NginxProcessesForExecutable -ExecutablePath $ExecutablePath)) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    return -not (Get-NginxProcessesForExecutable -ExecutablePath $ExecutablePath)
}

function Stop-NginxProcessesForExecutable {
    param([Parameter(Mandatory = $true)][string]$ExecutablePath)

    $processes = Get-NginxProcessesForExecutable -ExecutablePath $ExecutablePath
    foreach ($process in $processes) {
        try {
            Write-Host "Stopping nginx PID $($process.ProcessId)" -ForegroundColor Yellow
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
        catch {
            if (-not (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) {
                continue
            }
            throw "Failed to stop nginx PID $($process.ProcessId). Run the launcher as Administrator or stop nginx manually. $($_.Exception.Message)"
        }
    }
}

function Start-NginxProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $nginxStartPreview = Format-CommandPreview -Executable $ExecutablePath -Arguments @("-c", $ConfigPath)
    if ($Preview) {
        Write-Host "[preview] starting nginx"
        Write-Host "  $nginxStartPreview"
        return
    }

    Start-Process -FilePath $ExecutablePath `
        -WorkingDirectory $WorkingDirectory `
        -ArgumentList @("-c", $ConfigPath) | Out-Null
}

function Restart-NginxProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $quitResult = Invoke-ExternalCommandResult `
        -Executable $ExecutablePath `
        -Arguments @("-s", "quit", "-c", $ConfigPath) `
        -WorkingDirectory $WorkingDirectory `
        -Description "Stopping nginx"

    if ($quitResult.ExitCode -ne 0) {
        Write-Warning "Graceful nginx stop failed with exit code $($quitResult.ExitCode). Trying direct process stop."
        Stop-NginxProcessesForExecutable -ExecutablePath $ExecutablePath
    }
    elseif (-not (Wait-ForNginxProcessesToExit -ExecutablePath $ExecutablePath)) {
        Write-Warning "nginx did not stop within the timeout. Trying direct process stop."
        Stop-NginxProcessesForExecutable -ExecutablePath $ExecutablePath
    }

    if (-not (Wait-ForNginxProcessesToExit -ExecutablePath $ExecutablePath)) {
        throw "nginx did not stop; cannot start a clean replacement."
    }

    Start-NginxProcess -ExecutablePath $ExecutablePath -ConfigPath $ConfigPath -WorkingDirectory $WorkingDirectory
}

function Wait-ForHttpSuccess {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Probe,
        [int]$TimeoutSeconds = 25,
        [int]$DelayMilliseconds = 1000
    )

    if ($Preview) {
        Write-Host "[preview] waiting for $Description"
        return
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $result = & $Probe
            if ($result) {
                return
            }
        }
        catch {
            $lastError = $_.Exception.Message
        }

        Start-Sleep -Milliseconds $DelayMilliseconds
    }

    if ($lastError) {
        throw "Timed out waiting for $Description. Last error: $lastError"
    }

    throw "Timed out waiting for $Description."
}

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$frontendRoot = Join-Path $resolvedRepoRoot "frontend"
$frontendNodeModules = Join-Path $frontendRoot "node_modules"
$frontendDistRoot = Join-Path $frontendRoot "dist"
$backendRequirements = Join-Path $resolvedRepoRoot "backend\requirements.txt"

$nginxCommand = Get-Command nginx -ErrorAction SilentlyContinue
$candidateNginxExePaths = @(
    $NginxExePath,
    $(if ($nginxCommand) { $nginxCommand.Source }),
    "C:\nginx\nginx.exe",
    "C:\Program Files\nginx\nginx.exe",
    "C:\Program Files (x86)\nginx\nginx.exe"
)
$resolvedNginxExePath = Select-FirstExistingPath -Candidates $candidateNginxExePaths

if (-not $resolvedNginxExePath) {
    if ($Preview) {
        $resolvedNginxExePath = $NginxExePath
    }
    else {
        throw "nginx.exe not found. Pass -NginxExePath with the real nginx.exe path."
    }
}

$candidateNginxConfPaths = @(
    $NginxConfPath,
    $(if ($resolvedNginxExePath -and (Test-Path -LiteralPath $resolvedNginxExePath)) { Join-Path (Split-Path -Parent $resolvedNginxExePath) "conf\nginx.conf" })
)
$resolvedNginxConfPath = Select-FirstExistingPath -Candidates $candidateNginxConfPaths

if (-not $resolvedNginxConfPath) {
    if ($Preview) {
        $resolvedNginxConfPath = $NginxConfPath
    }
    else {
        throw "nginx.conf not found. Pass -NginxConfPath with the real nginx.conf path."
    }
}

$nginxWorkingDirectory = Split-Path -Parent $resolvedNginxExePath

if (-not (Test-Path -LiteralPath (Join-Path $resolvedRepoRoot ".git"))) {
    throw "Git repository not found: $resolvedRepoRoot"
}

if (-not (Test-Path -LiteralPath $frontendRoot)) {
    throw "Frontend directory not found: $frontendRoot"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is not available in PATH"
}

if (-not $SkipPull) {
    $gitStatus = & git -C $resolvedRepoRoot status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to read git status for $resolvedRepoRoot"
    }

    if ($gitStatus) {
        Write-Warning "Repository has local changes. Skipping git pull to avoid merge conflicts."
    }
    else {
        Invoke-ExternalCommand `
            -Executable "git" `
            -Arguments @("-C", $resolvedRepoRoot, "pull", "--ff-only") `
            -WorkingDirectory $resolvedRepoRoot `
            -Description "Updating repository"
    }
}

if ($Bootstrap) {
    $backendInstallArgs = @()
    if ($BackendPythonVersion) {
        $backendInstallArgs += $BackendPythonVersion
    }
    $backendInstallArgs += @("-m", "pip", "install", "-r", $backendRequirements)
    Invoke-ExternalCommand `
        -Executable $BackendPythonLauncher `
        -Arguments $backendInstallArgs `
        -WorkingDirectory $resolvedRepoRoot `
        -Description "Installing backend dependencies"

    $gateInstallArgs = @()
    if ($GatePythonVersion) {
        $gateInstallArgs += $GatePythonVersion
    }
    $gateInstallArgs += @("-m", "pip", "install", "pyodbc", "python-dotenv")
    Invoke-ExternalCommand `
        -Executable $GatePythonLauncher `
        -Arguments $gateInstallArgs `
        -WorkingDirectory $resolvedRepoRoot `
        -Description "Installing Gate diagnostic dependencies"
}

if ($Bootstrap -or -not (Test-Path -LiteralPath $frontendNodeModules)) {
    Invoke-ExternalCommand `
        -Executable "npm" `
        -Arguments @("install") `
        -WorkingDirectory $frontendRoot `
        -Description "Installing frontend dependencies"
}

$previousUseRealApi = $env:EXPO_PUBLIC_USE_REAL_API
$previousApiBaseUrl = $env:EXPO_PUBLIC_API_BASE_URL

try {
    $env:EXPO_PUBLIC_USE_REAL_API = $FrontendUseRealApi.ToString().ToLower()
    $env:EXPO_PUBLIC_API_BASE_URL = $FrontendApiBaseUrl
    Invoke-ExternalCommand `
        -Executable "npx" `
        -Arguments @("expo", "export", "--platform", "web", "--output-dir", "dist") `
        -WorkingDirectory $frontendRoot `
        -Description "Building frontend production bundle"
    & (Join-Path $resolvedRepoRoot "scripts\copy_latest_apk_to_dist.ps1") -RepoRoot $resolvedRepoRoot
}
finally {
    if ($null -eq $previousUseRealApi) {
        Remove-Item Env:EXPO_PUBLIC_USE_REAL_API -ErrorAction SilentlyContinue
    }
    else {
        $env:EXPO_PUBLIC_USE_REAL_API = $previousUseRealApi
    }

    if ($null -eq $previousApiBaseUrl) {
        Remove-Item Env:EXPO_PUBLIC_API_BASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:EXPO_PUBLIC_API_BASE_URL = $previousApiBaseUrl
    }
}

if ($Preview) {
    Write-Host "[preview] verify frontend build output at $(Join-Path $frontendDistRoot 'index.html')"
}
elseif (-not (Test-Path -LiteralPath (Join-Path $frontendDistRoot "index.html"))) {
    throw "Frontend build is missing frontend/dist/index.html"
}

$backendBody = @(
    "Remove-Item Env:ALLOWED_HOSTS_JSON -ErrorAction SilentlyContinue",
    "Remove-Item Env:CORS_ALLOW_ORIGINS_JSON -ErrorAction SilentlyContinue",
    "`$pythonArgs = @()",
    $(if ($BackendPythonVersion) { "`$pythonArgs += $(Quote-PowerShellLiteral -Value $BackendPythonVersion)" } else { "`$pythonArgs += @()" }),
    "`$pythonArgs += @('-m', 'uvicorn', 'backend.app.main:app', '--host', $(Quote-PowerShellLiteral -Value $BackendHost), '--port', $(Quote-PowerShellLiteral -Value $BackendPort.ToString()))",
    "& $(Quote-PowerShellLiteral -Value $BackendPythonLauncher) @pythonArgs"
)

Start-WorkspaceWindow -Title "Savoya Backend" -WorkingDirectory $resolvedRepoRoot -Body $backendBody

Wait-ForHttpSuccess -Description "backend health endpoint" -Probe {
    $result = Invoke-CurlRequest -Arguments @(
        "-sS",
        "http://127.0.0.1:$BackendPort/health"
    ) -AllowFailure
    return $result.ExitCode -eq 0 -and $result.Output -match '"status"\s*:\s*"ok"'
}

Invoke-ExternalCommand `
    -Executable $resolvedNginxExePath `
    -Arguments @("-t", "-c", $resolvedNginxConfPath) `
    -WorkingDirectory $nginxWorkingDirectory `
    -Description "Testing nginx configuration"

$nginxProcess = Get-Process -Name "nginx" -ErrorAction SilentlyContinue
if ($nginxProcess) {
    $reloadResult = Invoke-ExternalCommandResult `
        -Executable $resolvedNginxExePath `
        -Arguments @("-s", "reload", "-c", $resolvedNginxConfPath) `
        -WorkingDirectory $nginxWorkingDirectory `
        -Description "Reloading nginx"

    if ($reloadResult.ExitCode -ne 0) {
        Write-Warning "Reloading nginx failed with exit code $($reloadResult.ExitCode). Restarting nginx instead."
        Restart-NginxProcess -ExecutablePath $resolvedNginxExePath -ConfigPath $resolvedNginxConfPath -WorkingDirectory $nginxWorkingDirectory
    }
}
else {
    Start-NginxProcess -ExecutablePath $resolvedNginxExePath -ConfigPath $resolvedNginxConfPath -WorkingDirectory $nginxWorkingDirectory
}

Wait-ForHttpSuccess -Description "nginx frontend root page" -Probe {
    $result = Invoke-CurlRequest -Arguments @(
        "-k",
        "-sS",
        "-I",
        "-H", "Host: $NginxServerName",
        "https://127.0.0.1/"
    ) -AllowFailure
    return $result.ExitCode -eq 0 -and $result.Output -match "200 OK"
}

Wait-ForHttpSuccess -Description "nginx health proxy" -Probe {
    $result = Invoke-CurlRequest -Arguments @(
        "-k",
        "-sS",
        "-H", "Host: $NginxServerName",
        "https://127.0.0.1/health"
    ) -AllowFailure
    return $result.ExitCode -eq 0 -and $result.Output -match '"status"\s*:\s*"ok"'
}

if ($OpenToolShell) {
    Start-WorkspaceWindow `
        -Title "Savoya Shell" `
        -WorkingDirectory $resolvedRepoRoot `
        -Body @("Write-Host 'Savoya shell is ready.' -ForegroundColor Green")
}
elseif ($Preview) {
    Write-Host "[preview] current shell remains available at $resolvedRepoRoot"
}
else {
    Set-Location -LiteralPath $resolvedRepoRoot
    Write-Host "Current shell is ready for project commands: $resolvedRepoRoot" -ForegroundColor Green
}

Write-Host "Frontend should be served by nginx on ports 80/443." -ForegroundColor Green
Write-Host "Backend should be reachable only from nginx at http://127.0.0.1:$BackendPort." -ForegroundColor Green
Write-Host "Verified: frontend/dist exists, backend health is OK, nginx / and /health respond through HTTPS." -ForegroundColor Green
