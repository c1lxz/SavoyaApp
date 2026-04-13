[CmdletBinding()]
param(
    [string]$ProxyHost = "127.0.0.1",
    [int]$HttpProxyPort = 0,
    [int]$SocksProxyPort = 0,
    [string]$ProxyServer = "",
    [string]$WorkingDirectory = "C:\Users\User\Desktop\SavoyaApp\SavoyaApp",
    [string]$NoProxy = "localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
    [string[]]$CodexArgs = @("--sandbox", "danger-full-access"),
    [switch]$AllowSamePublicIp,
    [switch]$CheckOnly,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"

function Stop-Safely {
    param([Parameter(Mandatory = $true)][string]$Message)

    throw $Message
}

function Get-InternetSettings {
    $internetSettingsPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $item = Get-ItemProperty -Path $internetSettingsPath -ErrorAction SilentlyContinue
    if (-not $item) {
        return [pscustomobject]@{
            ProxyEnable = 0
            ProxyServer = ""
        }
    }

    return [pscustomobject]@{
        ProxyEnable = [int]$item.ProxyEnable
        ProxyServer = [string]$item.ProxyServer
    }
}

function Parse-ProxyServerValue {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$DefaultHost
    )

    $result = @{
        HttpHost = $null
        HttpPort = 0
        SocksHost = $null
        SocksPort = 0
    }

    $rawEntries = $Value -split ';'
    foreach ($rawEntry in $rawEntries) {
        $entry = $rawEntry.Trim()
        if (-not $entry) {
            continue
        }

        $kind = ""
        $address = $entry

        if ($entry -match '=') {
            $kind, $address = $entry -split '=', 2
            $kind = $kind.Trim().ToLowerInvariant()
            $address = $address.Trim()
        }

        if ($address -match '^(?<scheme>https?|socks5?)://(?<rest>.+)$') {
            if (-not $kind) {
                $kind = $matches.scheme.Trim().ToLowerInvariant()
            }
            $address = $matches.rest.Trim()
        }

        if (-not ($address -match '^(?<host>\[[^\]]+\]|[^:]+):(?<port>\d+)$')) {
            continue
        }

        $parsedHost = $matches.host.Trim()
        $port = [int]$matches.port
        if (-not $parsedHost) {
            $parsedHost = $DefaultHost
        }

        switch ($kind) {
            "http" {
                $result.HttpHost = $parsedHost
                $result.HttpPort = $port
                continue
            }
            "https" {
                if (-not $result.HttpPort) {
                    $result.HttpHost = $parsedHost
                    $result.HttpPort = $port
                }
                continue
            }
            "socks" {
                $result.SocksHost = $parsedHost
                $result.SocksPort = $port
                continue
            }
            "socks5" {
                $result.SocksHost = $parsedHost
                $result.SocksPort = $port
                continue
            }
            default {
                if (-not $result.HttpPort) {
                    $result.HttpHost = $parsedHost
                    $result.HttpPort = $port
                }
                if (-not $result.SocksPort) {
                    $result.SocksHost = $parsedHost
                    $result.SocksPort = $port
                }
            }
        }
    }

    return $result
}

function Format-ProxyEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Scheme,
        [Parameter(Mandatory = $true)][string]$ProxyHostName,
        [Parameter(Mandatory = $true)][int]$Port
    )

    return "{0}://{1}:{2}" -f $Scheme, $ProxyHostName, $Port
}

function Resolve-WorkingDirectory {
    param([Parameter(Mandatory = $true)][string]$Value)

    return [System.IO.Path]::GetFullPath($Value)
}

function Test-CurlAvailability {
    $curl = Get-Command "curl.exe" -ErrorAction SilentlyContinue
    if (-not $curl) {
        Stop-Safely "curl.exe not found. Install curl or run without proxy connectivity checks."
    }
    return $curl.Source
}

function Test-LoopbackHost {
    param([Parameter(Mandatory = $true)][string]$Value)

    $normalized = $Value.Trim().TrimStart('[').TrimEnd(']').ToLowerInvariant()
    return $normalized -in @("127.0.0.1", "::1", "localhost")
}

function Get-ListeningProxy {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $listeners) {
        Stop-Safely "No listening TCP socket found on local port $Port. Connect happ first."
    }

    $safeListener = $listeners | Where-Object {
        $_.LocalAddress -in @("127.0.0.1", "::1")
    } | Select-Object -First 1

    if (-not $safeListener) {
        $addresses = ($listeners | Select-Object -ExpandProperty LocalAddress -Unique) -join ", "
        Stop-Safely "Port $Port is listening on non-loopback address(es): $addresses. Refusing to use it."
    }

    $owner = Get-Process -Id $safeListener.OwningProcess -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        LocalAddress = $safeListener.LocalAddress
        LocalPort = $safeListener.LocalPort
        ProcessId = $safeListener.OwningProcess
        ProcessName = $(if ($owner) { $owner.ProcessName } else { "" })
        ProcessPath = $(if ($owner) { $owner.Path } else { "" })
    }
}

function Get-DangerousDefaultRoutes {
    $pattern = '(?i)(^|[^a-z])(tun|tap|wintun|wireguard|zerotier|tailscale|clash|sing-box|singbox|xray|v2ray|vpn)([^a-z]|$)'
    $dangerous = @()

    foreach ($prefix in @("0.0.0.0/0", "::/0")) {
        $routes = Get-NetRoute -DestinationPrefix $prefix -ErrorAction SilentlyContinue
        foreach ($route in $routes) {
            $adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
            $alias = [string]$route.InterfaceAlias
            $description = $(if ($adapter) { [string]$adapter.InterfaceDescription } else { "" })
            $combined = "$alias $description"
            if ($combined -match $pattern) {
                $dangerous += [pscustomobject]@{
                    DestinationPrefix = $route.DestinationPrefix
                    NextHop = $route.NextHop
                    InterfaceAlias = $alias
                    InterfaceDescription = $description
                    RouteMetric = $route.RouteMetric
                }
            }
        }
    }

    return $dangerous
}

function Invoke-ProxyRequest {
    param(
        [Parameter(Mandatory = $true)][string]$CurlExecutable,
        [string]$ProxyUri,
        [switch]$Direct
    )

    $arguments = @("--silent", "--show-error", "--max-time", "15")
    if ($Direct) {
        $arguments += @("--noproxy", "*")
    }
    elseif ($ProxyUri) {
        $arguments += @("--proxy", $ProxyUri)
    }
    $arguments += "https://ifconfig.me"

    $output = & $CurlExecutable @arguments
    if ($LASTEXITCODE -ne 0) {
        $mode = $(if ($Direct) { "direct" } else { "proxy" })
        Stop-Safely "curl check failed in $mode mode."
    }

    return [string]$output
}

$internetSettings = Get-InternetSettings
$resolvedWorkingDirectory = Resolve-WorkingDirectory -Value $WorkingDirectory
if (-not (Test-Path -LiteralPath $resolvedWorkingDirectory)) {
    Stop-Safely "WorkingDirectory not found: $resolvedWorkingDirectory"
}

if (-not $ProxyServer) {
    $ProxyServer = $internetSettings.ProxyServer
}

if (($HttpProxyPort -le 0) -and ($SocksProxyPort -le 0) -and $ProxyServer) {
    $parsedProxy = Parse-ProxyServerValue -Value $ProxyServer -DefaultHost $ProxyHost
    if ($parsedProxy.HttpPort -gt 0) {
        $HttpProxyPort = $parsedProxy.HttpPort
        if ($parsedProxy.HttpHost) {
            $ProxyHost = $parsedProxy.HttpHost
        }
    }
    elseif ($parsedProxy.SocksPort -gt 0) {
        $SocksProxyPort = $parsedProxy.SocksPort
        if ($parsedProxy.SocksHost) {
            $ProxyHost = $parsedProxy.SocksHost
        }
    }
}

if (($HttpProxyPort -le 0) -and ($SocksProxyPort -le 0)) {
    Stop-Safely @"
Proxy port was not resolved.

Pass one of these options explicitly:
  -HttpProxyPort 7890
  -SocksProxyPort 7891

Or temporarily enable "System Proxy" in happ, connect once, and run:
  Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' | Select-Object ProxyEnable,ProxyServer
"@
}

if (-not (Test-LoopbackHost -Value $ProxyHost)) {
    Stop-Safely "Proxy host must stay on localhost/127.0.0.1/::1. Current value: $ProxyHost"
}

$proxyUri = $null
$proxyKind = $null
$proxyPort = 0
if ($HttpProxyPort -gt 0) {
    $proxyUri = Format-ProxyEndpoint -Scheme "http" -ProxyHostName $ProxyHost -Port $HttpProxyPort
    $proxyKind = "HTTP"
    $proxyPort = $HttpProxyPort
}
else {
    $proxyUri = Format-ProxyEndpoint -Scheme "socks5" -ProxyHostName $ProxyHost -Port $SocksProxyPort
    $proxyKind = "SOCKS5"
    $proxyPort = $SocksProxyPort
}

$proxyListener = Get-ListeningProxy -Port $proxyPort
$dangerousRoutes = Get-DangerousDefaultRoutes
if ($dangerousRoutes.Count -gt 0) {
    $routeSummary = ($dangerousRoutes | ForEach-Object {
        "{0} via {1} ({2})" -f $_.DestinationPrefix, $_.NextHop, $_.InterfaceAlias
    }) -join "; "
    Stop-Safely "Dangerous default route detected on a TUN/VPN-style adapter: $routeSummary"
}

if ($internetSettings.ProxyEnable -ne 0) {
    Stop-Safely "Windows System Proxy is enabled. Disable it in happ before running Codex."
}

$codexCommand = Get-Command "codex" -ErrorAction SilentlyContinue
if (-not $codexCommand) {
    Stop-Safely "codex command not found in PATH."
}

$curlExecutable = Test-CurlAvailability
$directIp = Invoke-ProxyRequest -CurlExecutable $curlExecutable -Direct
$proxyIp = Invoke-ProxyRequest -CurlExecutable $curlExecutable -ProxyUri $proxyUri

Write-Host "WorkingDirectory: $resolvedWorkingDirectory"
Write-Host "Proxy type: $proxyKind"
Write-Host "Proxy endpoint: $proxyUri"
Write-Host "Proxy listener: $($proxyListener.LocalAddress):$($proxyListener.LocalPort) pid=$($proxyListener.ProcessId) $($proxyListener.ProcessName)"
if ($proxyListener.ProcessPath) {
    Write-Host "Proxy process path: $($proxyListener.ProcessPath)"
}
Write-Host "System Proxy enabled: $($internetSettings.ProxyEnable)"
if ($ProxyServer) {
    Write-Host "Registry ProxyServer: $ProxyServer"
}
Write-Host "Direct IP: $directIp"
Write-Host "Proxy IP: $proxyIp"
if ($directIp -eq $proxyIp) {
    if (-not $AllowSamePublicIp) {
        Stop-Safely "Direct IP and proxy IP are identical. happ is likely disconnected or not tunneling Codex traffic."
    }
    Write-Warning "Direct IP and proxy IP are identical, but launch is allowed because -AllowSamePublicIp was set."
}

if ($Preview) {
    if ($HttpProxyPort -gt 0) {
        Write-Host ('$env:HTTP_PROXY="{0}"' -f $proxyUri)
        Write-Host ('$env:HTTPS_PROXY="{0}"' -f $proxyUri)
    }
    else {
        Write-Host ('$env:ALL_PROXY="{0}"' -f $proxyUri)
    }
    Write-Host ('$env:NO_PROXY="{0}"' -f $NoProxy)
    Write-Host "Set-Location -LiteralPath '$resolvedWorkingDirectory'"
    Write-Host ("codex {0}" -f ($CodexArgs -join " "))
    return
}

if ($CheckOnly) {
    return
}

if ($HttpProxyPort -gt 0) {
    $env:HTTP_PROXY = $proxyUri
    $env:HTTPS_PROXY = $proxyUri
    Remove-Item Env:ALL_PROXY -ErrorAction SilentlyContinue
}
else {
    $env:ALL_PROXY = $proxyUri
    Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
    Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
}
$env:NO_PROXY = $NoProxy

Push-Location -LiteralPath $resolvedWorkingDirectory
try {
    & $codexCommand.Source @CodexArgs
    if ($LASTEXITCODE -ne 0) {
        Stop-Safely "codex exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
