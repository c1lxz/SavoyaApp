param(
    [string]$Domain = "ipksavoya.ru",
    [string]$HealthUrl = "https://ipksavoya.ru/health",
    [string]$ExpectedIp = ""
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
Write-Host "== HTTP =="
try {
    $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 10
    Write-Host "StatusCode: $($response.StatusCode)"
    Write-Host $response.Content
}
catch {
    if ($_.Exception.Response) {
        Write-Host "StatusCode: $([int]$_.Exception.Response.StatusCode)"
    }
    Write-Host "HTTP check failed: $($_.Exception.Message)"
}
