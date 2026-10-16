param(
    [ValidateSet("development", "public", "production")]
    [string]$RuntimeMode = $env:FAMAS_RUNTIME_MODE,
    [switch]$RunDatabaseCheck,
    [switch]$RequireFrontendBuild,
    [switch]$RequireGpu
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeMode) {
    $RuntimeMode = "development"
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$WebDir = Join-Path $ProjectRoot "web"
$BackendDir = Join-Path $WebDir "backend"
$FrontendDir = Join-Path $WebDir "frontend"
$StorageDir = Join-Path $WebDir "storage"
$FrontendDistIndex = Join-Path $FrontendDir "dist\index.html"
. (Join-Path $PSScriptRoot "_python-paths.ps1")

$script:PassCount = 0
$script:WarnCount = 0
$script:FailCount = 0

function Write-Check {
    param(
        [ValidateSet("PASS", "WARN", "FAIL")]
        [string]$Level,
        [string]$Message
    )

    switch ($Level) {
        "PASS" {
            $script:PassCount += 1
            Write-Host "[PASS] $Message" -ForegroundColor Green
        }
        "WARN" {
            $script:WarnCount += 1
            Write-Host "[WARN] $Message" -ForegroundColor Yellow
        }
        "FAIL" {
            $script:FailCount += 1
            Write-Host "[FAIL] $Message" -ForegroundColor Red
        }
    }
}

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-SecretStrength {
    param([string]$Secret)

    if (-not $Secret) {
        return $false
    }
    if ($Secret -in @("dev-secret", "dev-only-change-me", "change-me-before-first-start")) {
        return $false
    }
    return $Secret.Length -ge 32
}

function Invoke-PythonCheck {
    param(
        [string]$Python,
        [string[]]$Arguments,
        [string]$PassMessage,
        [string]$FailMessage
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $Python @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            Write-Check "PASS" $PassMessage
            return $output
        }
        Write-Check "FAIL" "$FailMessage ($output)"
    } catch {
        Write-Check "FAIL" "$FailMessage ($($_.Exception.Message))"
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return $null
}

Write-Host ""
Write-Host "FaMAS deployment readiness check" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Runtime mode: $RuntimeMode"
Write-Host ""

if (Test-Path $BackendDir) {
    Write-Check "PASS" "Backend directory exists: $BackendDir"
} else {
    Write-Check "FAIL" "Backend directory is missing: $BackendDir"
}

if (Test-Path $FrontendDir) {
    Write-Check "PASS" "Frontend directory exists: $FrontendDir"
} else {
    Write-Check "FAIL" "Frontend directory is missing: $FrontendDir"
}

$BackendPython = Resolve-FaMASBackendPython -ProjectRoot $ProjectRoot
if ($BackendPython -eq "python" -or (Test-Path $BackendPython)) {
    Write-Check "PASS" "Backend Python resolved: $BackendPython"
} else {
    Write-Check "FAIL" "Backend Python does not exist: $BackendPython"
}

Invoke-PythonCheck `
    -Python $BackendPython `
    -Arguments @("-c", "import fastapi, sqlalchemy, alembic, cryptography, jwt; print('ok')") `
    -PassMessage "Backend Python imports required packages" `
    -FailMessage "Backend Python cannot import required packages" | Out-Null

if (Test-CommandAvailable "node") {
    $nodeVersion = (& node --version 2>$null)
    Write-Check "PASS" "Node is available: $nodeVersion"
} else {
    Write-Check "FAIL" "Node is not available in PATH"
}

if (Test-CommandAvailable "npm") {
    $npmVersion = (& npm --version 2>$null)
    Write-Check "PASS" "npm is available: $npmVersion"
} else {
    Write-Check "FAIL" "npm is not available in PATH"
}

if (Test-Path (Join-Path $FrontendDir "package.json")) {
    Write-Check "PASS" "Frontend package.json exists"
} else {
    Write-Check "FAIL" "Frontend package.json is missing"
}

if (Test-Path $FrontendDistIndex) {
    Write-Check "PASS" "Frontend build exists: web\frontend\dist\index.html"
} elseif ($RequireFrontendBuild) {
    Write-Check "FAIL" "Frontend build is missing; run npm run build in web\frontend"
} else {
    Write-Check "WARN" "Frontend build is missing; single-port/public mode needs npm run build"
}

if (-not (Test-Path $StorageDir)) {
    New-Item -ItemType Directory -Path $StorageDir -Force | Out-Null
}

$writeProbe = Join-Path $StorageDir ".readiness-write-test"
try {
    Set-Content -Path $writeProbe -Value "ok" -Encoding ASCII
    Remove-Item -Path $writeProbe -Force
    Write-Check "PASS" "Storage directory is writable: $StorageDir"
} catch {
    Write-Check "FAIL" "Storage directory is not writable: $StorageDir ($($_.Exception.Message))"
}

$PipelinePython = Resolve-FaMASPipelinePython -ProjectRoot $ProjectRoot
if ($PipelinePython -and (Test-Path $PipelinePython)) {
    Write-Check "PASS" "Pipeline Python resolved: $PipelinePython"
    try {
        $torchOutput = & $PipelinePython -c "import torch; print('cuda=' + str(torch.cuda.is_available()))" 2>&1
        if ($LASTEXITCODE -eq 0) {
            if (($torchOutput -join "`n") -match "cuda=True") {
                Write-Check "PASS" "Pipeline PyTorch CUDA is available"
            } elseif ($RequireGpu) {
                Write-Check "FAIL" "Pipeline PyTorch is available but CUDA is not enabled"
            } else {
                Write-Check "WARN" "Pipeline PyTorch CUDA is not available; image/PDF processing may run on CPU"
            }
        } elseif ($RequireGpu) {
            Write-Check "FAIL" "Pipeline Python cannot import torch: $torchOutput"
        } else {
            Write-Check "WARN" "Pipeline Python cannot import torch; GPU check skipped"
        }
    } catch {
        if ($RequireGpu) {
            Write-Check "FAIL" "Pipeline GPU check failed: $($_.Exception.Message)"
        } else {
            Write-Check "WARN" "Pipeline GPU check skipped: $($_.Exception.Message)"
        }
    }
} elseif ($PipelinePython) {
    Write-Check "FAIL" "Pipeline Python does not exist: $PipelinePython"
} else {
    Write-Check "WARN" "Pipeline Python was not found; backend will fall back to its own interpreter"
}

$secretOk = Test-SecretStrength $env:FAMAS_SECRET_KEY
if ($RuntimeMode -in @("public", "production")) {
    if ($secretOk) {
        Write-Check "PASS" "FAMAS_SECRET_KEY is set and looks non-default"
    } else {
        Write-Check "FAIL" "FAMAS_SECRET_KEY must be a stable non-default value of at least 32 characters"
    }

    if ($env:FAMAS_ENABLE_DIAGNOSTICS -eq "1") {
        Write-Check "WARN" "FAMAS_ENABLE_DIAGNOSTICS=1 exposes local path diagnostics; use 0 for public/production"
    } else {
        Write-Check "PASS" "Diagnostics are not explicitly enabled"
    }
} elseif ($secretOk) {
    Write-Check "PASS" "FAMAS_SECRET_KEY is set and looks non-default"
} else {
    Write-Check "WARN" "FAMAS_SECRET_KEY is unset or weak; acceptable only for short local development"
}

if ($env:FAMAS_SECRET_ENCRYPTION_KEY) {
    if (Test-SecretStrength $env:FAMAS_SECRET_ENCRYPTION_KEY) {
        Write-Check "PASS" "FAMAS_SECRET_ENCRYPTION_KEY is set and looks non-default"
    } else {
        Write-Check "WARN" "FAMAS_SECRET_ENCRYPTION_KEY is set but weak"
    }
} else {
    Write-Check "WARN" "FAMAS_SECRET_ENCRYPTION_KEY is unset; API-key encryption falls back to FAMAS_SECRET_KEY"
}

if ($env:FAMAS_DATABASE_URL) {
    Write-Check "PASS" "FAMAS_DATABASE_URL is set"
} else {
    Write-Check "WARN" "FAMAS_DATABASE_URL is unset; default SQLite database under web\storage will be used"
}

$maxUploadBytes = $env:FAMAS_MAX_UPLOAD_BYTES
if ($maxUploadBytes) {
    $parsedMaxUpload = 0L
    if ([long]::TryParse($maxUploadBytes, [ref]$parsedMaxUpload) -and $parsedMaxUpload -ge 31457280) {
        Write-Check "PASS" "FAMAS_MAX_UPLOAD_BYTES allows files larger than 30 MiB"
    } else {
        Write-Check "WARN" "FAMAS_MAX_UPLOAD_BYTES is below 30 MiB or not numeric"
    }
} else {
    Write-Check "PASS" "Default upload limit is 250 MiB"
}

if ($RunDatabaseCheck) {
    Push-Location $BackendDir
    try {
        Invoke-PythonCheck `
            -Python $BackendPython `
            -Arguments @("-m", "alembic", "check") `
            -PassMessage "Alembic model/database metadata check passed" `
            -FailMessage "Alembic check failed" | Out-Null
    } finally {
        Pop-Location
    }
} else {
    Write-Check "WARN" "Database migration check skipped; rerun with -RunDatabaseCheck before deployment"
}

Write-Host ""
Write-Host "Summary: $script:PassCount passed, $script:WarnCount warnings, $script:FailCount failed"

if ($script:FailCount -gt 0) {
    exit 1
}
