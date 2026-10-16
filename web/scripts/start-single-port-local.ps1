param(
    [string]$SecretKey = $env:FAMAS_SECRET_KEY,
    [string]$AdminPassword = $env:FAMAS_ADMIN_PASSWORD,
    [string]$RegistrationMode = "immediate",
    [int]$WorkerConcurrency = 1,
    [switch]$NoBackendReload,
    [switch]$Mock
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$FrontendDir = Join-Path $ProjectRoot "web\frontend"
$BackendDir = Join-Path $ProjectRoot "web\backend"
. (Join-Path $PSScriptRoot "_project-config.ps1")
. (Join-Path $PSScriptRoot "_python-paths.ps1")
if ($WorkerConcurrency -lt 1) {
    throw "WorkerConcurrency must be at least 1."
}

$localSecrets = Resolve-FaMASLocalSecrets -ProjectName "famas" -SecretKey $SecretKey -AdminPassword $AdminPassword
$SecretKey = $localSecrets.SecretKey
$AdminPassword = $localSecrets.AdminPassword

$BackendVenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$PipelineVenvPython = Join-Path $ProjectRoot "code_implement\.venv\Scripts\python.exe"
$FrontendNodeModules = Join-Path $FrontendDir "node_modules"

if (-not (Test-Path $BackendVenvPython)) {
    Write-Host "Missing backend environment. Run: .\web\scripts\setup-backend-env.ps1" -ForegroundColor Yellow
    return
}
if (-not (Test-Path $PipelineVenvPython)) {
    Write-Host "Missing pipeline environment. Run: .\web\scripts\setup-pipeline-env.ps1" -ForegroundColor Yellow
    return
}
if (-not (Test-Path $FrontendNodeModules)) {
    Write-Host "Missing frontend dependencies. Run: cd web\frontend; npm install" -ForegroundColor Yellow
    return
}

Set-Location $FrontendDir
Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
& npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Frontend build failed. Run: cd web\frontend; npm install" -ForegroundColor Yellow
    return
}

$env:FAMAS_SECRET_KEY = $SecretKey
$env:FAMAS_RUNTIME_MODE = "development"
$env:PYTHONUNBUFFERED = "1"
$env:FAMAS_PIPELINE_WORKER_CONCURRENCY = [string]$WorkerConcurrency
if ($AdminPassword) {
    $env:FAMAS_ADMIN_PASSWORD = $AdminPassword
}
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

Write-Host ""
Write-Host "FaMAS single-port local server" -ForegroundColor Cyan
Write-Host "Local URL:    http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Health URL:   http://127.0.0.1:8000/api/health" -ForegroundColor Green
Write-Host "Ready URL:    http://127.0.0.1:8000/api/health/ready" -ForegroundColor Green
Write-Host "Runtime mode: development"
Write-Host "Frontend mode: built snapshot from web\frontend\dist"
Write-Host "Pipeline worker concurrency: $WorkerConcurrency"
Write-Host "Backend Python: $Python"
if ($PipelinePython) {
    Write-Host "Pipeline Python: $PipelinePython"
}
Write-Host "Local config:  $($localSecrets.Path)" -ForegroundColor DarkGray
if ($NoBackendReload) {
    Write-Host "Backend reload: off"
} else {
    Write-Host "Backend reload: on (backend code changes restart the API server)"
}
Write-Host "Note: frontend source changes are not hot-reloaded in single-port mode; restart this script after changing Vue/CSS/chemistry viewer files." -ForegroundColor Yellow
Write-Host "Note: the terminal prints backend HTTP/API requests. Pure browser-side tab switches may not produce new lines." -ForegroundColor Yellow
Write-Host "Preflight: .\web\scripts\check-deployment-readiness.ps1 -RunDatabaseCheck -RequireFrontendBuild" -ForegroundColor DarkGray
Write-Host "Backup:    .\web\scripts\backup-local-data.ps1" -ForegroundColor DarkGray
Write-Host "Stopping any old process that is listening on port 8000..."
Stop-FaMASPortListener -Port 8000
Set-Location $BackendDir
Write-Host "Starting backend. Keep this terminal open. Request logs should appear below after startup." -ForegroundColor Cyan
$UvicornArgs = @(
    "app.main:app",
    "--host", "127.0.0.1",
    "--port", "8000",
    "--log-level", "info",
    "--access-log"
)
if (-not $NoBackendReload) {
    $UvicornArgs += @("--reload", "--reload-dir", $BackendDir)
}
& $Python -m uvicorn @UvicornArgs
