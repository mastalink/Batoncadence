# MCOrchestr8 one-shot setup (Windows PowerShell).
# Creates the venv, installs the package editable with dev extras, and verifies
# the CLI resolves to the venv - sidestepping any global `uv`/`pipx` shim that
# might shadow `mco` on PATH.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtualenv (.venv)..." -ForegroundColor Cyan
    python -m venv .venv
}

$py = Join-Path $root ".venv\Scripts\python.exe"
Write-Host "Installing MCOrchestr8 (editable, with dev extras)..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install -e ".[dev]"

Write-Host "`nVerifying CLI via the venv interpreter..." -ForegroundColor Cyan
& $py -m mco.cli --help | Select-Object -First 3

Write-Host "`nDone. Always invoke the CLI as:" -ForegroundColor Green
Write-Host "    .venv\Scripts\python.exe -m mco.cli <command>" -ForegroundColor Green
Write-Host "or use scripts\mco.ps1 (a thin wrapper that does exactly that)." -ForegroundColor Green
