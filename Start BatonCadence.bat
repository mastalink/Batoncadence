@echo off
REM ============================================================================
REM Start BatonCadence
REM ============================================================================
REM Starts the BatonCadence gateway and opens the console GUI in your browser.
REM Close this window to stop BatonCadence.
REM ============================================================================
cd /d "%~dp0"
title BatonCadence Server

if not exist ".venv\Scripts\python.exe" (
    echo BatonCadence is not installed yet. Double-click install.bat first.
    pause
    exit /b 1
)

REM If a server is already running, just open the console and exit.
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18789/healthz -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    echo BatonCadence is already running. Opening the console...
    start "" http://127.0.0.1:18789/console
    exit /b 0
)

echo Starting BatonCadence... your browser will open in a few seconds.
echo Keep this window open. Close it to stop BatonCadence.
echo.

REM Open the console GUI once the server has had a moment to start.
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:18789/console"

".venv\Scripts\python.exe" -m mco.cli serve
