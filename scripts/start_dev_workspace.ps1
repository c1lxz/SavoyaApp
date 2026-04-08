[CmdletBinding()]
param(
    [string]$RepoRoot = $(Split-Path -Parent $PSScriptRoot),
    [switch]$SkipPull,
    [switch]$Bootstrap,
    [switch]$OpenToolShell,
    [switch]$Preview,
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [string]$BackendPythonLauncher = "py",
    [string]$BackendPythonVersion = "-3.12",
    [bool]$FrontendUseRealApi = $true,
    [string]$FrontendApiBaseUrl = "",
    [string]$GatePythonLauncher = "py",
    [string]$GatePythonVersion = "-3.12-32"
)

$ErrorActionPreference = "Stop"

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

    $preview = Format-CommandPreview -Executable $Executable -Arguments $Arguments
    if ($Preview) {
        Write-Host "[preview] $Description"
        Write-Host "  $preview"
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
        Write-Host "  powershell.exe -NoExit -ExecutionPolicy Bypass -Command $command"
        return
    }

    Start-Process -FilePath "powershell.exe" `
        -WorkingDirectory $WorkingDirectory `
        -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $command) | Out-Null
}

function Resolve-FrontendApiBaseUrl {
    param(
        [Parameter(Mandatory = $true)][string]$ApiHost,
        [Parameter(Mandatory = $true)][int]$Port,
        [string]$ConfiguredBaseUrl
    )

    if ($ConfiguredBaseUrl) {
        return $ConfiguredBaseUrl.Trim()
    }

    $apiHost = $ApiHost.Trim()
    if ($apiHost -in @("0.0.0.0", "::", "[::]")) {
        $apiHost = "127.0.0.1"
    }

    return "http://{0}:{1}/api" -f $apiHost, $Port
}

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$frontendRoot = Join-Path $resolvedRepoRoot "frontend"
$resolvedFrontendApiBaseUrl = Resolve-FrontendApiBaseUrl `
    -ApiHost $BackendHost `
    -Port $BackendPort `
    -ConfiguredBaseUrl $FrontendApiBaseUrl

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

$backendRequirements = Join-Path $resolvedRepoRoot "backend\requirements.txt"
$frontendNodeModules = Join-Path $frontendRoot "node_modules"

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

$backendBody = @(
    "`$pythonArgs = @()",
    $(if ($BackendPythonVersion) { "`$pythonArgs += $(Quote-PowerShellLiteral -Value $BackendPythonVersion)" } else { "`$pythonArgs += @()" }),
    "`$pythonArgs += @('-m', 'uvicorn', 'backend.app.main:app', '--host', $(Quote-PowerShellLiteral -Value $BackendHost), '--port', $(Quote-PowerShellLiteral -Value $BackendPort.ToString()))",
    "& $(Quote-PowerShellLiteral -Value $BackendPythonLauncher) @pythonArgs"
)

$frontendBody = @(
    "`$env:EXPO_PUBLIC_USE_REAL_API = $(Quote-PowerShellLiteral -Value $FrontendUseRealApi.ToString().ToLower())",
    "`$env:EXPO_PUBLIC_API_BASE_URL = $(Quote-PowerShellLiteral -Value $resolvedFrontendApiBaseUrl)",
    "if (-not (Test-Path -LiteralPath 'node_modules')) { npm install }",
    "npm run web"
)

Start-WorkspaceWindow -Title "Savoya Backend" -WorkingDirectory $resolvedRepoRoot -Body $backendBody
Start-WorkspaceWindow -Title "Savoya Frontend" -WorkingDirectory $frontendRoot -Body $frontendBody

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
