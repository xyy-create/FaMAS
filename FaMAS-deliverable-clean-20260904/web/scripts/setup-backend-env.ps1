param(
    [string]$Python = "python",
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$BackendDir = Join-Path $ProjectRoot "web\backend"
$VenvDir = Join-Path $BackendDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    & $Python -m venv $VenvDir
}

& $VenvPython -m pip install --upgrade pip

if ($Dev) {
    & $VenvPython -m pip install -r (Join-Path $BackendDir "requirements-dev.txt")
} else {
    & $VenvPython -m pip install -r (Join-Path $BackendDir "requirements.txt")
}

Write-Host "Backend environment ready: $VenvPython"
