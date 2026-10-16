param(
    [string]$SecretKey = $env:FAMAS_SECRET_KEY,
    [string]$AdminPassword = $env:FAMAS_ADMIN_PASSWORD,
    [string]$PublicUrl = "",
    [int]$WorkerConcurrency = 1,
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

if ($SecretKey -in @("dev-secret", "dev-only-change-me")) {
    throw "Use a stronger SecretKey before temporary public access."
}
if ($SecretKey.Length -lt 32) {
    throw "FAMAS_SECRET_KEY must be at least 32 characters before temporary public access."
}

$BackendVenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$FrontendNodeModules = Join-Path $FrontendDir "node_modules"
if (-not (Test-Path $BackendVenvPython)) {
    Write-Host "Missing backend environment. Run: .\web\scripts\setup-backend-env.ps1" -ForegroundColor Yellow
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
$env:FAMAS_RUNTIME_MODE = "public"
$env:PYTHONUNBUFFERED = "1"
$env:FAMAS_PIPELINE_WORKER_CONCURRENCY = [string]$WorkerConcurrency
$env:FAMAS_ADMIN_PASSWORD = $AdminPassword
$env:FAMAS_REGISTRATION_MODE = "approval"
$env:FAMAS_PUBLIC_URL = $PublicUrl
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
Write-Host "FaMAS temporary public review server" -ForegroundColor Cyan
Write-Host "Local URL:    http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Health URL:   http://127.0.0.1:8000/api/health" -ForegroundColor Green
Write-Host "Ready URL:    http://127.0.0.1:8000/api/health/ready" -ForegroundColor Green
if ($PublicUrl) {
    Write-Host "Public URL:   $PublicUrl" -ForegroundColor Green
} else {
    Write-Host "Public URL:   not configured" -ForegroundColor Yellow
    Write-Host "Next step: start a tunnel or reverse proxy to http://127.0.0.1:8000 and rerun with -PublicUrl." -ForegroundColor Yellow
}
Write-Host "Runtime mode: public"
Write-Host "Frontend mode: built snapshot from web\frontend\dist"
Write-Host "Backend reload: off (keeps public review runs stable)"
Write-Host "Pipeline worker concurrency: $WorkerConcurrency"
Write-Host "Backend Python: $Python"
if ($PipelinePython) {
    Write-Host "Pipeline Python: $PipelinePython"
}
Write-Host "Note: frontend source changes are not hot-reloaded in public review mode; restart this script after changing Vue/CSS/chemistry viewer files." -ForegroundColor Yellow
Write-Host "Note: the terminal prints backend HTTP/API requests. Pure browser-side tab switches may not produce new lines." -ForegroundColor Yellow
Write-Host "Preflight: .\web\scripts\check-deployment-readiness.ps1 -RuntimeMode public -RunDatabaseCheck -RequireFrontendBuild" -ForegroundColor DarkGray
Write-Host "Backup:    .\web\scripts\backup-local-data.ps1" -ForegroundColor DarkGray
Write-Host "Stopping any old process that is listening on port 8000..."
Stop-FaMASPortListener -Port 8000
Set-Location $BackendDir
Write-Host "Starting backend. Keep this terminal open. Request logs should appear below after startup." -ForegroundColor Cyan
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info --access-log
