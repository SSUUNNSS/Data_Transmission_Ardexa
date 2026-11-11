$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runner = Join-Path $PSScriptRoot "upload_hams_hall_station.py"
$logDirectory = Join-Path $projectRoot "logs"
$logPath = Join-Path $logDirectory "hams_hall_powershell.log"
$mutex = New-Object System.Threading.Mutex($false, "Local\ArdexaHamsHallScheduledUpload")
$hasMutex = $false

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

try {
    $hasMutex = $mutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $hasMutex = $true
}

if (-not $hasMutex) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')] SKIP another upload cycle is already running"
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
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}