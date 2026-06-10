@echo off
REM ============================================================================
REM BatonCadence One-Click Installer
REM ============================================================================
REM Double-click this file to install BatonCadence on Windows.
REM It runs scripts\install.ps1, which:
REM   1. Finds (or installs) Python 3.9+
REM   2. Creates a private virtual environment (.venv)
REM   3. Installs BatonCadence and its dependencies
REM   4. Writes a safe Local-Only configuration (.env)
REM   5. Puts a "BatonCadence" shortcut on your Desktop
REM ============================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
echo.
pause
