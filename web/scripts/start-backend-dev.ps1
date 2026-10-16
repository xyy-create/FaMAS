param(
    [string]$SecretKey = $env:FAMAS_SECRET_KEY,
    [string]$AdminPassword = $env:FAMAS_ADMIN_PASSWORD,
    [string]$RegistrationMode = "immediate",
    [switch]$Mock
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$BackendDir = Join-Path $ProjectRoot "web\backend"
. (Join-Path $PSScriptRoot "_project-config.ps1")
. (Join-Path $PSScriptRoot "_python-paths.ps1")

$localSecrets = Resolve-FaMASLocalSecrets -ProjectName "famas" -SecretKey $SecretKey -AdminPassword $AdminPassword
$SecretKey = $localSecrets.SecretKey
$AdminPassword = $localSecrets.AdminPassword

$BackendVenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $BackendVenvPython)) {
    Write-Host "Missing backend environment. Run: .\web\scripts\setup-backend-env.ps1" -ForegroundColor Yellow
    return
}

$env:FAMAS_SECRET_KEY = $SecretKey
$env:FAMAS_RUNTIME_MODE = "development"
$env:FAMAS_ADMIN_PASSWORD = $AdminPassword
$env:FAMAS_REGISTRATION_MODE = $RegistrationMode
$PipelinePython = Resolve-FaMASPipelinePython -ProjectRoot $ProjectRoot
if ($PipelinePython) {
    $env:FAMAS_PIPELINE_PYTHON = $PipelinePython
}
if ($Mock) {
    $env:FAMAS_PIPELINE_MOCK = "1"
} else {
    Remove-Item Env:FAMAS_PIPELINE_MOCK -ErrorAction SilentlyContinue
}

$Python = $BackendVenvPython

Stop-FaMASPortListener -Port 8000
Set-Location $BackendDir
& $Python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
