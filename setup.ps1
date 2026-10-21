$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
}
& '.venv\Scripts\python.exe' -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit $LASTEXITCODE)." }
& '.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed (exit $LASTEXITCODE)." }
Write-Host "`nStudyShip environment is ready. Run start.bat to launch." -ForegroundColor Green
