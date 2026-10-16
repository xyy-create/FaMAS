param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"

function Join-UrlPath {
    param(
        [string]$Base,
        [string]$Path
    )

    return $Base.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

function Invoke-JsonGet {
    param(
        [string]$Url,
        [int]$TimeoutSeconds
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec $TimeoutSeconds -UseBasicParsing
        return @{
            ok = $true
            status_code = [int]$response.StatusCode
            body = $response.Content | ConvertFrom-Json
        }
    } catch {
        $statusCode = 0
        if ($_.Exception.Response) {
            try {
                $statusCode = [int]$_.Exception.Response.StatusCode
            } catch {
                $statusCode = 0
            }
        }
        return @{
            ok = $false
            status_code = $statusCode
            error = $_.Exception.Message
        }
    }
}

$healthUrl = Join-UrlPath -Base $BaseUrl -Path "/api/health"
$readyUrl = Join-UrlPath -Base $BaseUrl -Path "/api/health/ready"

Write-Host ""
Write-Host "FaMAS running server check" -ForegroundColor Cyan
Write-Host "Base URL: $BaseUrl"
Write-Host ""

$health = Invoke-JsonGet -Url $healthUrl -TimeoutSeconds $TimeoutSeconds
if ($health.ok -and $health.status_code -eq 200) {
    Write-Host "[PASS] /api/health responded with HTTP 200" -ForegroundColor Green
} else {
    Write-Host "[FAIL] /api/health did not respond successfully: $($health.error)" -ForegroundColor Red
    exit 1
}

$ready = Invoke-JsonGet -Url $readyUrl -TimeoutSeconds $TimeoutSeconds
if ($ready.ok -and $ready.status_code -eq 200) {
    Write-Host "[PASS] /api/health/ready responded with HTTP 200" -ForegroundColor Green
    Write-Host ("Status: " + $ready.body.status)
    Write-Host ("Checks: " + ($ready.body.checks | ConvertTo-Json -Compress))
    exit 0
}

Write-Host "[FAIL] /api/health/ready did not report ready" -ForegroundColor Red
if ($ready.status_code) {
    Write-Host "HTTP status: $($ready.status_code)"
}
if ($ready.body) {
    Write-Host ("Body: " + ($ready.body | ConvertTo-Json -Compress))
} elseif ($ready.error) {
    Write-Host "Error: $($ready.error)"
}
exit 1
