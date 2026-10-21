$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        Write-Host 'First run: installing Python dependencies...' -ForegroundColor Cyan
        & "$Root\setup.ps1"
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed (exit $LASTEXITCODE)." }
    }

    if (Test-Path '.env') {
        Get-Content '.env' | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
                $parts = $line.Split('=', 2)
                [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
            }
        }
    }

    $BindHost = if ($env:STUDYSHIP_HOST) { $env:STUDYSHIP_HOST } else { '127.0.0.1' }
    $Port = if ($env:STUDYSHIP_PORT) { $env:STUDYSHIP_PORT } else { '8765' }
    $Url = "http://${BindHost}:$Port"
    Write-Host "StudyShip starting at $Url" -ForegroundColor Green
    Start-Process $Url
    & '.venv\Scripts\python.exe' -m uvicorn app.main:app --host $BindHost --port $Port
    if ($LASTEXITCODE -ne 0) { throw "StudyShip exited with code $LASTEXITCODE." }
}
catch {
    Write-Host ''
    Write-Host "STARTUP ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Run setup.ps1 first if Python dependencies are missing.' -ForegroundColor Yellow
    exit 1
}
