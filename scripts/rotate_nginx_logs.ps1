[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$NginxRoot,
    [long]$MaxBytes = 100MB
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $NginxRoot).Path
$executable = Join-Path $root 'nginx.exe'
$config = Join-Path $root 'conf\nginx.conf'
$logs = (Resolve-Path -LiteralPath (Join-Path $root 'logs')).Path
$files = @(Get-Item -LiteralPath (Join-Path $logs 'access.log'),(Join-Path $logs 'error.log') |
    Where-Object { $_.Length -ge $MaxBytes })
if (-not $files) { exit 0 }

Push-Location $root
try {
    & $executable -t -c $config
    if ($LASTEXITCODE -ne 0) { throw 'Nginx config validation failed' }
    $archive = Join-Path $logs 'archive'
    New-Item -ItemType Directory -Path $archive -Force | Out-Null
    $archive = (Resolve-Path -LiteralPath $archive).Path
    if (-not $archive.StartsWith($logs + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Archive directory is outside nginx logs'
    }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stopped = $false
    try {
        foreach ($file in $files) {
            $target = Join-Path $archive ($file.BaseName + '-' + $stamp + '.log')
            try {
                Move-Item -LiteralPath $file.FullName -Destination $target -ErrorAction Stop
            } catch {
                # Windows can refuse renaming an open log. Stop this nginx
                # installation gracefully before moving its file.
                & $executable -s quit -c $config
                if ($LASTEXITCODE -ne 0) { throw 'Nginx graceful stop failed' }
                $stopped = $true
                $deadline = (Get-Date).AddSeconds(20)
                do {
                    $running = @(Get-CimInstance Win32_Process -Filter "Name='nginx.exe'" |
                        Where-Object { $_.ExecutablePath -ieq $executable })
                    if (-not $running) { break }
                    Start-Sleep -Milliseconds 500
                } while ((Get-Date) -lt $deadline)
                if ($running) { throw 'Nginx did not exit gracefully' }
                Move-Item -LiteralPath $file.FullName -Destination $target -ErrorAction Stop
            }
            Write-Output "Archived $($file.Name) ($($file.Length) bytes) to $target"
        }
    } finally {
        if ($stopped) {
            $stillRunning = @(Get-CimInstance Win32_Process -Filter "Name='nginx.exe'" |
                Where-Object { $_.ExecutablePath -ieq $executable })
            if (-not $stillRunning) {
                Start-Process -FilePath $executable -WorkingDirectory $root -ArgumentList @('-c', $config) -WindowStyle Hidden
            }
        } else {
            & $executable -s reopen -c $config
            if ($LASTEXITCODE -ne 0) { throw 'Nginx log reopen failed' }
        }
    }
} finally {
    Pop-Location
}
