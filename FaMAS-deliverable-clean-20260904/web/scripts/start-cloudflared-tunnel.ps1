param(
    [string]$TargetUrl = "http://127.0.0.1:8000",
    [string]$CloudflaredPath = "",
    [ValidateSet("http2", "quic", "auto")]
    [string]$Protocol = "http2"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

if (-not $CloudflaredPath) {
    $localExe = Join-Path $ProjectRoot "tools\cloudflared\cloudflared.exe"
    $localAmd64Exe = Join-Path $ProjectRoot "tools\cloudflared\cloudflared-windows-amd64.exe"
    if (Test-Path $localExe) {
        $CloudflaredPath = $localExe
    } elseif (Test-Path $localAmd64Exe) {
        $CloudflaredPath = $localAmd64Exe
    } else {
        $command = Get-Command cloudflared -ErrorAction SilentlyContinue
        if ($command) {
            $CloudflaredPath = $command.Source
        }
    }
}

if (-not $CloudflaredPath -or -not (Test-Path $CloudflaredPath)) {
    Write-Host "cloudflared was not found." -ForegroundColor Yellow
    Write-Host "Run: .\web\scripts\setup-cloudflared.ps1" -ForegroundColor Yellow
    return
}

Write-Host "Starting Cloudflare Quick Tunnel" -ForegroundColor Cyan
Write-Host "Target URL: $TargetUrl" -ForegroundColor Green
Write-Host "Copy the generated https://*.trycloudflare.com URL." -ForegroundColor Yellow
& $CloudflaredPath tunnel --protocol $Protocol --url $TargetUrl
