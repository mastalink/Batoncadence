# Thin, shim-proof wrapper: always runs the CLI through the project venv's
# interpreter, from the repo root, so relative paths (e.g. configs\workflows\*)
# and the `mco` entrypoint resolve correctly no matter your current directory
# or what `where mco` finds first.
#
#   scripts\mco.ps1 serve
#   scripts\mco.ps1 workflow configs\workflows\qa_loop.yaml --dry-run
#   scripts\mco.ps1 approve <job_id>
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "No venv found. Run scripts\setup.ps1 first."
    exit 1
}
Push-Location $root
try {
    & $py -m mco.cli @args
} finally {
    Pop-Location
}
