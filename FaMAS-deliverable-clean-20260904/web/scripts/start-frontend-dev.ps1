$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$FrontendDir = Join-Path $ProjectRoot "web\frontend"

Set-Location $FrontendDir
npm run dev
