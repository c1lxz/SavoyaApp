param(
    [string]$Domain = "xn--80aaachc8cmu1au8c1f.xn--p1ai",
    [string]$HealthUrl = "http://xn--80aaachc8cmu1au8c1f.xn--p1ai/health"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "== DNS =="
try {
    Resolve-DnsName -Name $Domain -Type A | Select-Object Name, IPAddress
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
