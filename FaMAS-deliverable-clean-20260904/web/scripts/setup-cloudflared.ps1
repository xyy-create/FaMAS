param(
    [string]$InstallDir = "",
    [string]$DownloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $InstallDir) {
    $InstallDir = Join-Path $ProjectRoot "tools\cloudflared"
}

$CloudflaredPath = Join-Path $InstallDir "cloudflared.exe"
if ((Test-Path $CloudflaredPath) -and -not $Force) {
    Write-Host "cloudflared already exists: $CloudflaredPath" -ForegroundColor Green
    & $CloudflaredPath --version
    return
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Write-Host "Downloading cloudflared from: $DownloadUrl" -ForegroundColor Cyan
Invoke-WebRequest -Uri $DownloadUrl -OutFile $CloudflaredPath

Write-Host "cloudflared ready: $CloudflaredPath" -ForegroundColor Green
& $CloudflaredPath --version
