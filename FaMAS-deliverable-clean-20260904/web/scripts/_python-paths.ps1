function Resolve-FaMASBackendPython {
    param(
        [string]$ProjectRoot,
        [string]$Python = $env:FAMAS_BACKEND_PYTHON
    )

    if ($Python) {
        return $Python
    }

    $backendPython = Join-Path $ProjectRoot "web\backend\.venv\Scripts\python.exe"
    if (Test-Path $backendPython) {
        return $backendPython
    }

    $pipelinePython = Join-Path $ProjectRoot "code_implement\.venv\Scripts\python.exe"
    if (Test-Path $pipelinePython) {
        return $pipelinePython
    }

    return "python"
}

function Resolve-FaMASPipelinePython {
    param(
        [string]$ProjectRoot,
        [string]$Python = $env:FAMAS_PIPELINE_PYTHON
    )

    if ($Python) {
        return $Python
    }

    $pipelinePython = Join-Path $ProjectRoot "code_implement\.venv\Scripts\python.exe"
    if (Test-Path $pipelinePython) {
        return $pipelinePython
    }

    return ""
}

function Stop-FaMASPortListener {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [int]$WaitSeconds = 10
    )

    $listenerPids = @()
    try {
        $listenerPids = & netstat -ano | Select-String "LISTENING" | ForEach-Object {
            $line = $_.Line.Trim()
            if ($line -match ":(?:$Port)\s+") {
                ($line -split "\s+")[-1]
            }
        } | Where-Object { $_ } | Sort-Object -Unique
    } catch {
        $listenerPids = @()
    }

    foreach ($pidText in $listenerPids) {
        $processId = 0
        if (-not [int]::TryParse([string]$pidText, [ref]$processId)) {
            continue
        }
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
        } catch {
            continue
        }
    }

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        $stillListening = $false
        try {
            $stillListening = [bool](& netstat -ano | Select-String "LISTENING" | Where-Object { $_.Line -match ":(?:$Port)\s+" })
        } catch {
            $stillListening = $false
        }
        if (-not $stillListening) {
            return
        }
        Start-Sleep -Milliseconds 250
    }

    Write-Host "Warning: port $Port still appears busy after waiting." -ForegroundColor Yellow
}
