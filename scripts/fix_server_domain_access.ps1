param(
    [string]$Domain = "ipksavoya.ru",
    [string]$WwwDomain = "www.ipksavoya.ru",
    [string]$HostsIp = "127.0.0.1",
    [bool]$PersistUserEnvironment = $true,
    [bool]$UpdateInternetSettings = $true,
    [bool]$UpdateHosts = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Merge-BypassValues {
    param(
        [string]$ExistingValue,
        [string[]]$AdditionalValues
    )

    $values = @()
    if ($ExistingValue) {
        $values += ($ExistingValue -split '[,;]' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    $values += ($AdditionalValues | ForEach-Object { $_.Trim() } | Where-Object { $_ })

    return ($values | Select-Object -Unique) -join ","
}

function Update-HostsMapping {
    param(
        [Parameter(Mandatory = $true)][string]$HostsPath,
        [Parameter(Mandatory = $true)][string]$IpAddress,
        [Parameter(Mandatory = $true)][string[]]$HostNames
    )

    $content = @()
    if (Test-Path -LiteralPath $HostsPath) {
        $content = Get-Content -LiteralPath $HostsPath
    }

    $escapedHosts = $HostNames | ForEach-Object { [regex]::Escape($_) }
    $hostPattern = '^\s*(?:\d{1,3}\.){3}\d{1,3}\s+.*\b(?:' + ($escapedHosts -join '|') + ')\b'
    $filtered = $content | Where-Object { $_ -notmatch $hostPattern }

    $filtered += ""
    foreach ($hostName in $HostNames) {
        $filtered += ("{0}`t{1}" -f $IpAddress, $hostName)
    }

    Set-Content -LiteralPath $HostsPath -Value $filtered -Encoding ASCII
}

$bypassHosts = @(
    $Domain,
    $WwwDomain,
    "localhost",
    "127.0.0.1",
    "::1"
) | Where-Object { $_ } | Select-Object -Unique

$bypassValue = Merge-BypassValues -ExistingValue $env:NO_PROXY -AdditionalValues $bypassHosts
$env:NO_PROXY = $bypassValue
$env:no_proxy = $bypassValue

Write-Host "Session proxy bypass updated:" -ForegroundColor Green
Write-Host ('$env:NO_PROXY="{0}"' -f $env:NO_PROXY)
Write-Host ('$env:no_proxy="{0}"' -f $env:no_proxy)

if ($PersistUserEnvironment) {
    [Environment]::SetEnvironmentVariable("NO_PROXY", $bypassValue, "User")
    [Environment]::SetEnvironmentVariable("no_proxy", $bypassValue, "User")
    Write-Host "User environment proxy bypass updated." -ForegroundColor Green
}

if ($UpdateInternetSettings) {
    $settingsPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $settings = Get-ItemProperty -Path $settingsPath -ErrorAction Stop
    $currentOverride = ""
    if ($null -ne $settings.PSObject.Properties["ProxyOverride"]) {
        $currentOverride = [string]$settings.ProxyOverride
    }
    $overrideValue = Merge-BypassValues -ExistingValue $currentOverride -AdditionalValues @($bypassHosts + "<local>")
    $overrideValue = ($overrideValue -split "," | Select-Object -Unique) -join ";"

    if ($null -eq $settings.PSObject.Properties["ProxyOverride"]) {
        New-ItemProperty -Path $settingsPath -Name ProxyOverride -PropertyType String -Value $overrideValue | Out-Null
    }
    else {
        Set-ItemProperty -Path $settingsPath -Name ProxyOverride -Value $overrideValue
    }
    Write-Host "Internet Settings ProxyOverride updated:" -ForegroundColor Green
    Write-Host $overrideValue
}

if ($UpdateHosts) {
    $hostsPath = Join-Path $env:WINDIR "System32\drivers\etc\hosts"
    try {
        Update-HostsMapping -HostsPath $hostsPath -IpAddress $HostsIp -HostNames @($Domain, $WwwDomain)
        Write-Host "hosts updated with $HostsIp for $Domain and $WwwDomain." -ForegroundColor Green
    }
    catch {
        Write-Warning "Failed to update hosts. Run this script as Administrator to pin the domain locally. $($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "Verification commands:"
Write-Host "  Resolve-DnsName $Domain -Type A"
Write-Host "  curl.exe --noproxy `"$Domain,$WwwDomain,127.0.0.1,localhost`" https://$Domain/health"
