param(
    [string]$Domain = "ipksavoya.ru",
    [string]$HealthUrl = "https://ipksavoya.ru/health",
    [string]$ExpectedIp = "",
    [string[]]$NoProxyHosts = @("127.0.0.1", "localhost", "::1", "ipksavoya.ru", "www.ipksavoya.ru")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsReservedBenchmarkIp {
    param([Parameter(Mandatory = $true)][string]$IpAddress)

    try {
        $bytes = [System.Net.IPAddress]::Parse($IpAddress).GetAddressBytes()
        return $bytes.Length -eq 4 -and $bytes[0] -eq 198 -and $bytes[1] -in 18, 19
    }
    catch {
        return $false
    }
}

function Test-IsNonPublicIpv6 {
    param([Parameter(Mandatory = $true)][string]$IpAddress)

    try {
        $address = [System.Net.IPAddress]::Parse($IpAddress)
        if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetworkV6) {
            return $false
        }

        $bytes = $address.GetAddressBytes()
        $firstByte = $bytes[0]

        # fc00::/7 unique local, fe80::/10 link-local, ::1 loopback
        if (($firstByte -band 0xFE) -eq 0xFC) {
            return $true
        }
        if ($firstByte -eq 0xFE -and ($bytes[1] -band 0xC0) -eq 0x80) {
            return $true
        }
        if ($address.IsIPv6LinkLocal -or $address.IsIPv6SiteLocal -or $address.IsIPv6Multicast) {
            return $true
        }
        if ($address.Equals([System.Net.IPAddress]::IPv6Loopback)) {
            return $true
        }

        return $false
    }
    catch {
        return $false
    }
}

function Invoke-HealthRequestWithoutProxy {
    param([Parameter(Mandatory = $true)][string]$Uri)

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $handler.AllowAutoRedirect = $true

    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(10)
    try {
        $response = $client.GetAsync($Uri).GetAwaiter().GetResult()
        $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()

        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Content = $content
        }
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

Write-Host "== DNS =="
$resolved = @()
try {
    $resolved = Resolve-DnsName -Name $Domain -Type A | Select-Object Name, IPAddress
    $resolved | Format-Table -AutoSize

    foreach ($row in $resolved) {
        if (Test-IsReservedBenchmarkIp -IpAddress $row.IPAddress) {
            Write-Warning "DNS points to reserved benchmark range 198.18.0.0/15: $($row.IPAddress). Replace the A record with the real public IP of the server."
        }
        elseif ($ExpectedIp -and $row.IPAddress -ne $ExpectedIp) {
            Write-Warning "Resolved IP $($row.IPAddress) does not match ExpectedIp $ExpectedIp."
        }
    }
}
catch {
    Write-Host "DNS lookup failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "== DNS AAAA =="
try {
    $resolvedIpv6 = Resolve-DnsName -Name $Domain -Type AAAA | Select-Object Name, IPAddress
    $resolvedIpv6 | Format-Table -AutoSize

    foreach ($row in $resolvedIpv6) {
        if (Test-IsNonPublicIpv6 -IpAddress $row.IPAddress) {
            Write-Warning "DNS AAAA record points to a non-public IPv6 address: $($row.IPAddress). Remove the AAAA record in DNS or replace it with a real public IPv6 address."
        }
    }
}
catch {
    Write-Host "AAAA lookup failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "== HTTP =="
try {
    $response = Invoke-HealthRequestWithoutProxy -Uri $HealthUrl
    Write-Host "StatusCode: $($response.StatusCode)"
    Write-Host $response.Content
}
catch {
    Write-Host "HTTP check failed without proxy: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "== Proxy Bypass =="
$normalizedNoProxyHosts = $NoProxyHosts | Where-Object { $_ } | Select-Object -Unique
Write-Host ('$env:NO_PROXY="{0}"' -f ($normalizedNoProxyHosts -join ","))
Write-Host ('$env:no_proxy="{0}"' -f ($normalizedNoProxyHosts -join ","))
