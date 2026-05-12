param(
    [Parameter(Mandatory = $true)]
    [string]$VehicleNumber,

    [string]$Action = "entry",

    [int]$AccessPointId,

    [switch]$OpenOnly
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $root "backend\app\scripts\simulate_vehicle_camera.py"

$arguments = @(
    "-3.12",
    $scriptPath,
    "--vehicle-number",
    $VehicleNumber
)

if ($PSBoundParameters.ContainsKey("AccessPointId")) {
    $arguments += @("--access-point-id", "$AccessPointId")
}
else {
    $arguments += @("--action", $Action)
}

if ($OpenOnly.IsPresent) {
    $arguments += "--open-only"
}

Push-Location $root
try {
    & py @arguments
}
finally {
    Pop-Location
}
