$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runner = Join-Path $PSScriptRoot "upload_hams_hall_station.py"
$logDirectory = Join-Path $projectRoot "logs"
$runId = "{0}_{1}_{2}" -f (Get-Date -Format "yyyyMMdd_HHmmss_fff"), $PID, ([guid]::NewGuid().ToString("N").Substring(0, 8))
$logPath = Join-Path $logDirectory "hams_hall_powershell_$runId.log"
$lockPath = Join-Path $logDirectory "hams_hall_upload.lock"
$lockStream = $null

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

try {
    $lockStream = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')] SKIP another upload cycle owns the global lock"
    exit 0
}

try {
$startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$startMessage = "[$startedAt] START Hams Hall 01-04 upload cycle"
Write-Host $startMessage
Add-Content -Path $logPath -Encoding UTF8 -Value $startMessage

try {
    & $python $runner 2>&1 | ForEach-Object {
        $line = $_.ToString()
        Write-Host $line
        Add-Content -Path $logPath -Encoding UTF8 -Value $line
    }
    $exitCode = $LASTEXITCODE
} catch {
    $errorMessage = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')] ERROR $($_.Exception.Message)"
    Write-Host $errorMessage -ForegroundColor Red
    Add-Content -Path $logPath -Encoding UTF8 -Value $errorMessage
    $exitCode = 1
}

$finishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$endMessage = "[$finishedAt] END exitCode=$exitCode"
Write-Host $endMessage
Add-Content -Path $logPath -Encoding UTF8 -Value $endMessage
exit $exitCode
} finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
}