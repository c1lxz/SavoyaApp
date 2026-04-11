[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [switch]$SkipPull,
    [switch]$Bootstrap,
    [switch]$OpenToolShell,
    [switch]$Preview,
    [string]$BackendHost = "0.0.0.0",
    [int]$BackendPort = 8000,
    [string]$BackendPythonLauncher = "py",
    [string]$BackendPythonVersion = "-3.12",
    [bool]$BootstrapDemoUser = $true,
    [string]$DemoLogin = "demo",
    [string]$DemoPassword = "demo123",
    [string]$DemoPhone = "+70000000000",
    [string]$DemoFullName = "Demo User",
    [string]$DemoPlotNumber = "25",
    [bool]$FrontendUseRealApi = $true,
    [string]$FrontendApiBaseUrl = "/api",
    [string]$GatePythonLauncher = "py",
    [string]$GatePythonVersion = "-3.12-32"
)

$ErrorActionPreference = "Stop"

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
        Write-Host "  powershell.exe -NoExit -ExecutionPolicy Bypass -EncodedCommand <base64>"
        Write-Host "  command: $command"
        return
    }

    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    Start-Process -FilePath "powershell.exe" `
        -WorkingDirectory $WorkingDirectory `
        -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encodedCommand) | Out-Null
}

function Get-LocalIpv4Addresses {
    $addresses = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
        Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
        ForEach-Object { $_.IPAddressToString } |
        Where-Object { $_ -and $_ -ne "127.0.0.1" }

    return @($addresses | Select-Object -Unique)
}

function Convert-ToJsonStringArrayLiteral {
    param([string[]]$Values)

    $escaped = @(
        foreach ($value in @($Values | Where-Object { $_ })) {
            '"' + ($value.Replace('\', '\\').Replace('"', '\"')) + '"'
        }
    )

    return "[" + ($escaped -join ",") + "]"
}

function Get-DotEnvJsonStringArray {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Key
    )

    $envPath = Join-Path $RepoRoot ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        return @()
    }

    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*=\s*(.+)\s*$'
    $line = Get-Content -LiteralPath $envPath | Where-Object { $_ -match $pattern } | Select-Object -Last 1
    if (-not $line) {
        return @()
    }

    $rawValue = [regex]::Match($line, $pattern).Groups[1].Value.Trim()
    if (-not $rawValue) {
        return @()
    }

    try {
        $parsed = ConvertFrom-Json -InputObject $rawValue
        return @($parsed | ForEach-Object { [string]$_ })
    }
    catch {
        return @()
    }
}

function Resolve-FrontendApiBaseUrl {
    param(
        [string]$ConfiguredBaseUrl
    )

    if ($ConfiguredBaseUrl) {
        return $ConfiguredBaseUrl.Trim()
    }

    return "/api"
}

function Build-BackendAllowedHostsJson {
    param(
        [string]$PrimaryApiBaseUrl,
        [string[]]$SeedHosts = @()
    )

    $hosts = @()
    foreach ($value in @($SeedHosts)) {
        if ($value -and $value -notin $hosts) {
            $hosts += $value
        }
    }

    foreach ($value in @("localhost", "127.0.0.1", "testserver", $env:COMPUTERNAME)) {
        if ($value -and $value -notin $hosts) {
            $hosts += $value
        }
    }

    foreach ($ip in Get-LocalIpv4Addresses) {
        if ($ip -and $ip -notin $hosts) {
            $hosts += $ip
        }
    }

    if ($PrimaryApiBaseUrl) {
        try {
            $uri = [System.Uri]$PrimaryApiBaseUrl
            if ($uri.Host -and $uri.Host -notin $hosts) {
                $hosts += $uri.Host
            }
        } catch {
            # Keep the default host list when the custom API URL is not a valid absolute URI.
        }
    }

    return Convert-ToJsonStringArrayLiteral -Values $hosts
}

function Build-BackendCorsOriginsJson {
    param(
        [string]$PrimaryApiBaseUrl,
        [string[]]$SeedOrigins = @()
    )

    $hosts = @()
    $origins = @()

    foreach ($origin in @($SeedOrigins)) {
        if ($origin -and $origin -notin $origins) {
            $origins += $origin
        }

        try {
            $uri = [System.Uri]$origin
            if ($uri.Host -and $uri.Host -notin $hosts) {
                $hosts += $uri.Host
            }
        } catch {
            # Ignore malformed origins from .env and keep the generated defaults.
        }
    }

    foreach ($value in @("localhost", "127.0.0.1", $env:COMPUTERNAME)) {
        if ($value -and $value -notin $hosts) {
            $hosts += $value
        }
    }

    foreach ($ip in Get-LocalIpv4Addresses) {
        if ($ip -and $ip -notin $hosts) {
            $hosts += $ip
        }
    }

    if ($PrimaryApiBaseUrl) {
        try {
            $uri = [System.Uri]$PrimaryApiBaseUrl
            if ($uri.Host -and $uri.Host -notin $hosts) {
                $hosts += $uri.Host
            }
        } catch {
            # Keep the default origin list when the custom API URL is not a valid absolute URI.
        }
    }

    $ports = @($null, 80, 8081, 8082, 8083, 19006)
    foreach ($hostName in $hosts) {
        foreach ($port in $ports) {
            $origin = if ($null -eq $port) { "http://$hostName" } else { "http://{0}:{1}" -f $hostName, $port }
            if ($origin -notin $origins) {
                $origins += $origin
            }
        }
    }

    return Convert-ToJsonStringArrayLiteral -Values $origins
}

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$frontendRoot = Join-Path $resolvedRepoRoot "frontend"
$resolvedFrontendApiBaseUrl = Resolve-FrontendApiBaseUrl `
    -ConfiguredBaseUrl $FrontendApiBaseUrl
$seedAllowedHosts = Get-DotEnvJsonStringArray -RepoRoot $resolvedRepoRoot -Key "ALLOWED_HOSTS_JSON"
$seedCorsOrigins = Get-DotEnvJsonStringArray -RepoRoot $resolvedRepoRoot -Key "CORS_ALLOW_ORIGINS_JSON"
$resolvedAllowedHostsJson = Build-BackendAllowedHostsJson `
    -PrimaryApiBaseUrl $resolvedFrontendApiBaseUrl `
    -SeedHosts $seedAllowedHosts
$resolvedCorsOriginsJson = Build-BackendCorsOriginsJson `
    -PrimaryApiBaseUrl $resolvedFrontendApiBaseUrl `
    -SeedOrigins $seedCorsOrigins
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

$frontendBuildArgs = @("expo", "export", "--platform", "web", "--output-dir", "dist")
$previousUseRealApi = $env:EXPO_PUBLIC_USE_REAL_API
$previousApiBaseUrl = $env:EXPO_PUBLIC_API_BASE_URL

try {
    $env:EXPO_PUBLIC_USE_REAL_API = $FrontendUseRealApi.ToString().ToLower()
    $env:EXPO_PUBLIC_API_BASE_URL = $resolvedFrontendApiBaseUrl
    Invoke-ExternalCommand `
        -Executable "npx" `
        -Arguments $frontendBuildArgs `
        -WorkingDirectory $frontendRoot `
        -Description "Building frontend production bundle"
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

$backendBody = @(
    "`$env:ALLOWED_HOSTS_JSON = $(Quote-PowerShellLiteral -Value $resolvedAllowedHostsJson)",
    "`$env:CORS_ALLOW_ORIGINS_JSON = $(Quote-PowerShellLiteral -Value $resolvedCorsOriginsJson)",
    "`$env:BOOTSTRAP_DEMO_USER = $(Quote-PowerShellLiteral -Value $BootstrapDemoUser.ToString().ToLower())",
    "`$env:DEMO_LOGIN = $(Quote-PowerShellLiteral -Value $DemoLogin)",
    "`$env:DEMO_PASSWORD = $(Quote-PowerShellLiteral -Value $DemoPassword)",
    "`$env:DEMO_PHONE = $(Quote-PowerShellLiteral -Value $DemoPhone)",
    "`$env:DEMO_FULL_NAME = $(Quote-PowerShellLiteral -Value $DemoFullName)",
    "`$env:DEMO_PLOT_NUMBER = $(Quote-PowerShellLiteral -Value $DemoPlotNumber)",
    "`$pythonArgs = @()",
    $(if ($BackendPythonVersion) { "`$pythonArgs += $(Quote-PowerShellLiteral -Value $BackendPythonVersion)" } else { "`$pythonArgs += @()" }),
    "`$pythonArgs += @('-m', 'uvicorn', 'backend.app.main:app', '--host', $(Quote-PowerShellLiteral -Value $BackendHost), '--port', $(Quote-PowerShellLiteral -Value $BackendPort.ToString()))",
    "& $(Quote-PowerShellLiteral -Value $BackendPythonLauncher) @pythonArgs"
)

Start-WorkspaceWindow -Title "Savoya Backend" -WorkingDirectory $resolvedRepoRoot -Body $backendBody

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

$accessHosts = @()
foreach ($accessHost in @($BackendHost, (Get-LocalIpv4Addresses), "127.0.0.1")) {
    if (-not $accessHost) {
        continue
    }

    if ($accessHost -in @("0.0.0.0", "::", "[::]")) {
        continue
    }

    if ($accessHost -notin $accessHosts) {
        $accessHosts += $accessHost
    }
}

if ($accessHosts.Count -gt 0) {
    Write-Host "Production frontend will be available at:" -ForegroundColor Green
    foreach ($accessHost in $accessHosts) {
        Write-Host ("  http://{0}:{1}/" -f $accessHost, $BackendPort) -ForegroundColor Green
    }
}
