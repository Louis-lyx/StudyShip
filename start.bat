@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
  echo.
  echo StudyShip startup failed. The error is shown above.
  pause
)
