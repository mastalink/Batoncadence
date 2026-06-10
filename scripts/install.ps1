# ============================================================================
# BatonCadence Setup Script (Windows)
# ============================================================================
# One-shot install, modeled on hermes' setup-hermes.sh:
#   1. Locates Python 3.9+ (offers to install it via winget if missing)
#   2. Creates a virtual environment (.venv)
#   3. Installs BatonCadence in editable mode
#   4. Creates a safe Local-Only .env (if none exists)
#   5. Creates a "BatonCadence" Desktop shortcut that starts the server
#      and opens the console GUI in the default browser
#   6. Offers to launch BatonCadence right away
#
# Usage (or just double-click install.bat in the repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# Pure ASCII output on purpose: legacy Windows consoles crash on unicode.
# ============================================================================
param(
    # Unattended mode: never prompt (used by CI / scripted installs).
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($m) { Write-Host "->  $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[!]  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[X]  $m" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  BatonCadence Setup" -ForegroundColor Cyan
Write-Host "  ==================" -ForegroundColor Cyan
Write-Host ""

# ----------------------------------------------------------------------------
# 1. Find Python 3.9+
# ----------------------------------------------------------------------------
Step "Checking for Python 3.9 or newer..."

function Find-Python {
    foreach ($cand in @("python", "py")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $exe = $cmd.Source
        $args = @()
        if ($cand -eq "py") { $args = @("-3") }
        & $exe @args -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return ,@($exe) + $args
        }
    }
    return $null
}

$pythonCmd = Find-Python
if ($pythonCmd) {
    $ver = & $pythonCmd[0] $pythonCmd[1..($pythonCmd.Count)] --version
    Ok "$ver found"
} else {
    Warn "Python 3.9+ was not found on this computer."
    if ($NoPrompt) { Fail "Python is required. Install it from https://www.python.org/downloads/ and retry." }
    $answer = Read-Host "Install Python automatically with winget? [Y/n]"
    if ($answer -eq "" -or $answer -match "^[Yy]") {
        Step "Installing Python via winget (this can take a few minutes)..."
        winget install --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        # Refresh PATH for this session so the new install is visible
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "User")
        $pythonCmd = Find-Python
        if (-not $pythonCmd) {
            Fail "Python was installed but is not yet visible. Close this window and run install.bat again."
        }
        Ok "Python installed"
    } else {
        Fail "Python is required. Install it from https://www.python.org/downloads/ and run install.bat again."
    }
}

# ----------------------------------------------------------------------------
# 2. Virtual environment
# ----------------------------------------------------------------------------
Step "Setting up the virtual environment (.venv)..."

if (-not (Test-Path (Join-Path $root ".venv\Scripts\python.exe"))) {
    & $pythonCmd[0] $pythonCmd[1..($pythonCmd.Count)] -m venv (Join-Path $root ".venv")
    Ok "Virtual environment created"
} else {
    Ok "Virtual environment already exists"
}

$py = Join-Path $root ".venv\Scripts\python.exe"

# ----------------------------------------------------------------------------
# 3. Install BatonCadence
# ----------------------------------------------------------------------------
Step "Installing BatonCadence and its dependencies (this can take a minute)..."

& $py -m pip install --upgrade pip --quiet
& $py -m pip install -e "$root" --quiet
if ($LASTEXITCODE -ne 0) { Fail "Dependency installation failed. Check your internet connection and retry." }
Ok "BatonCadence installed"

# ----------------------------------------------------------------------------
# 4. Configuration (.env) - safe Local-Only default, no cloud, no secrets
# ----------------------------------------------------------------------------
$envPath = Join-Path $root ".env"
if (-not (Test-Path $envPath)) {
    # Generate a secure local access token (used in place of a database token).
    $localToken = "mco_tok_" + (& $py -c "import secrets; print(secrets.token_hex(24))")
    Set-Content -Path $envPath -Encoding ascii -Value @(
        "# BatonCadence configuration (created by install.ps1)",
        "# Local-Only profile: everything runs on this computer, no database",
        "# or cloud account needed. Run 'mco setup' later to change profiles.",
        "MCO_PROFILE=Local-Only",
        "OPERATOR_NAME=$env:USERNAME",
        "MCO_LOCAL_TOKEN=$localToken"
    )
    Ok "Created Local-Only configuration (.env) with access token"
} else {
    # Add MCO_LOCAL_TOKEN if it is missing from an existing .env
    $envContent = Get-Content $envPath -Raw
    if ($envContent -notmatch 'MCO_LOCAL_TOKEN') {
        $localToken = "mco_tok_" + (& $py -c "import secrets; print(secrets.token_hex(24))")
        Add-Content -Path $envPath -Encoding ascii -Value "MCO_LOCAL_TOKEN=$localToken"
        Ok "Added MCO_LOCAL_TOKEN to existing .env"
    } else {
        Ok "Configuration (.env) already exists - leaving it untouched"
    }
}

# ----------------------------------------------------------------------------
# 5. Smoke test - make sure the CLI actually imports and runs
# ----------------------------------------------------------------------------
Step "Verifying the installation..."
& $py -m mco.cli --help | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "The mco CLI failed its self-check." }
Ok "CLI self-check passed"

# ----------------------------------------------------------------------------
# 6. Desktop shortcut -> "Start BatonCadence.bat"
# ----------------------------------------------------------------------------
Step "Creating the Desktop shortcut..."

$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktop "BatonCadence.lnk"))
$shortcut.TargetPath = Join-Path $root "Start BatonCadence.bat"
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Start BatonCadence and open the console GUI"
$shortcut.Save()
Ok "Shortcut 'BatonCadence' added to the Desktop"

# ----------------------------------------------------------------------------
# Done
# ----------------------------------------------------------------------------
Write-Host ""
Ok "Setup complete!"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Double-click the 'BatonCadence' icon on your Desktop."
Write-Host "  2. Your browser opens the console at http://127.0.0.1:18789/console"
Write-Host "  3. To stop BatonCadence, close its black server window."
Write-Host ""
Write-Host "Power-user commands (from this folder):" -ForegroundColor Cyan
Write-Host "  .venv\Scripts\python.exe -m mco.cli setup    # interactive wizard (profiles, encryption)"
Write-Host "  .venv\Scripts\python.exe -m mco.cli status   # configuration health check"
Write-Host "  .venv\Scripts\python.exe -m mco.cli serve    # run the gateway in the foreground"
Write-Host ""

if (-not $NoPrompt) {
    $answer = Read-Host "Would you like to start BatonCadence now? [Y/n]"
    if ($answer -eq "" -or $answer -match "^[Yy]") {
        Start-Process -FilePath (Join-Path $root "Start BatonCadence.bat") -WorkingDirectory $root
    }
}
