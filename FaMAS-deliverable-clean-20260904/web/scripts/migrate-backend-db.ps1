param(
    [string]$DatabaseUrl = $env:FAMAS_DATABASE_URL,
    [string]$Python = $env:FAMAS_BACKEND_PYTHON,
    [switch]$CheckOnly,
    [switch]$SkipCheck
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$BackendDir = Join-Path $ProjectRoot "web\backend"
. (Join-Path $PSScriptRoot "_python-paths.ps1")

if ($DatabaseUrl) {
    $env:FAMAS_DATABASE_URL = $DatabaseUrl
}

$Python = Resolve-FaMASBackendPython -ProjectRoot $ProjectRoot -Python $Python

Write-Host ""
Write-Host "FaMAS backend database migration" -ForegroundColor Cyan
Write-Host "Backend Python: $Python"
if ($DatabaseUrl) {
    Write-Host "Database URL: configured by FAMAS_DATABASE_URL"
} else {
    Write-Host "Database URL: default backend setting"
}
Write-Host ""

Set-Location $BackendDir

if ($CheckOnly) {
    Write-Host "Checking Alembic metadata..." -ForegroundColor Cyan
    & $Python -m alembic check
    exit $LASTEXITCODE
}

Write-Host "Applying migrations to head..." -ForegroundColor Cyan
& $Python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not $SkipCheck) {
    Write-Host ""
    Write-Host "Checking Alembic metadata after migration..." -ForegroundColor Cyan
    & $Python -m alembic check
    exit $LASTEXITCODE
}
