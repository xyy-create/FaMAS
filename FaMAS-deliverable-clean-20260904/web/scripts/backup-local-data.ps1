param(
    [string]$OutputDir = "",
    [switch]$IncludePipelineOutput,
    [switch]$IncludePipelineIntermediate,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$StorageDir = Join-Path $ProjectRoot "web\storage"
$PipelineOutputDir = Join-Path $ProjectRoot "code_implement\data\output"
$PipelineIntermediateDir = Join-Path $ProjectRoot "code_implement\data\intermediate"

if (-not $OutputDir) {
    $OutputDir = Join-Path $ProjectRoot ".tmp\backups"
}

$backupItems = @()
if (Test-Path $StorageDir) {
    $backupItems += $StorageDir
}
if ($IncludePipelineOutput -and (Test-Path $PipelineOutputDir)) {
    $backupItems += $PipelineOutputDir
}
if ($IncludePipelineIntermediate -and (Test-Path $PipelineIntermediateDir)) {
    $backupItems += $PipelineIntermediateDir
}

Write-Host ""
Write-Host "FaMAS local data backup" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Output dir:   $OutputDir"
Write-Host ""

if ($backupItems.Count -eq 0) {
    Write-Host "No backup source directories exist yet." -ForegroundColor Yellow
    exit 0
}

Write-Host "Backup sources:"
foreach ($item in $backupItems) {
    Write-Host "  - $item"
}

Write-Host ""
Write-Host "Recommendation: stop the backend before a final migration backup so the SQLite database is not being written during compression." -ForegroundColor Yellow

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run only. No archive was created." -ForegroundColor Cyan
    exit 0
}

if (-not (Get-Command Compress-Archive -ErrorAction SilentlyContinue)) {
    throw "Compress-Archive is not available in this PowerShell environment."
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archivePath = Join-Path $OutputDir "famas-local-data-$timestamp.zip"

Compress-Archive -Path $backupItems -DestinationPath $archivePath -CompressionLevel Optimal -Force

Write-Host ""
Write-Host "Backup created:" -ForegroundColor Green
Write-Host $archivePath
