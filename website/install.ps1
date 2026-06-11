# ============================================================================
# BatonCadence - Windows bootstrap installer
# ============================================================================
# Usage (run in PowerShell):
#   iwr -useb https://batoncadence.com/install.ps1 | iex
#
# What this does:
#   1. Clones the repo to $HOME\BatonCadence (or pulls updates if it exists)
#   2. Hands off to scripts\install.ps1 for the real setup
# ============================================================================
$ErrorActionPreference = "Stop"

$REPO = "https://github.com/mastalink/Batoncadence"
$DEST = if ($env:BATONCADENCE_INSTALL_DIR) { $env:BATONCADENCE_INSTALL_DIR } else { "$HOME\BatonCadence" }

Write-Host ""
Write-Host "  BatonCadence installer" -ForegroundColor Cyan
Write-Host "  =======================" -ForegroundColor Cyan
Write-Host ""

if (Test-Path (Join-Path $DEST ".git")) {
    Write-Host "->  Found existing install at $DEST - pulling updates..." -ForegroundColor Cyan
    try {
        git -C $DEST pull --ff-only origin main 2>$null
        Write-Host "[OK] Updated" -ForegroundColor Green
    } catch {
        Write-Host "[!]  Could not pull (offline or local changes). Continuing with current version." -ForegroundColor Yellow
    }
} else {
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCmd) {
        Write-Host "[X]  git is required. Install it from https://git-scm.com/ and retry." -ForegroundColor Red
        Write-Host "     Or download the ZIP directly from: $REPO" -ForegroundColor DarkGray
        exit 1
    }
    if ((Test-Path $DEST) -and (Get-ChildItem $DEST -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        Write-Host "[X]  $DEST exists and is not empty." -ForegroundColor Red
        Write-Host "     Move it or set `$env:BATONCADENCE_INSTALL_DIR to a different path." -ForegroundColor DarkGray
        exit 1
    }
    Write-Host "->  Cloning BatonCadence to $DEST..." -ForegroundColor Cyan
    git clone --depth 1 $REPO $DEST
    Write-Host "[OK] Repository ready at $DEST" -ForegroundColor Green
}

Write-Host ""
& powershell -ExecutionPolicy Bypass -File (Join-Path $DEST "scripts\install.ps1")
