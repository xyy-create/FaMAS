function Get-FaMASProjectConfigRoot {
    param(
        [string]$ProjectName = "famas"
    )

    return Join-Path $HOME ".famas\$ProjectName"
}

function Get-FaMASProjectConfigPath {
    param(
        [string]$ProjectName = "famas"
    )

    return Join-Path (Get-FaMASProjectConfigRoot -ProjectName $ProjectName) "local-config.json"
}

function Read-FaMASProjectConfig {
    param(
        [string]$ProjectName = "famas"
    )

    $configPath = Get-FaMASProjectConfigPath -ProjectName $ProjectName
    if (-not (Test-Path $configPath)) {
        return [pscustomobject]@{
            SecretKey = ""
            AdminPassword = ""
            Path = $configPath
        }
    }

    try {
        $raw = Get-Content -Path $configPath -Raw -Encoding UTF8
        $config = $raw | ConvertFrom-Json
        $secretKey = ""
        $adminPassword = ""
        if ($null -ne $config.FAMAS_SECRET_KEY) {
            $secretKey = [string]$config.FAMAS_SECRET_KEY
        }
        if ($null -ne $config.FAMAS_ADMIN_PASSWORD) {
            $adminPassword = [string]$config.FAMAS_ADMIN_PASSWORD
        }
        return [pscustomobject]@{
            SecretKey = $secretKey
            AdminPassword = $adminPassword
            Path = $configPath
        }
    } catch {
        return [pscustomobject]@{
            SecretKey = ""
            AdminPassword = ""
            Path = $configPath
        }
    }
}

function Save-FaMASProjectConfig {
    param(
        [string]$SecretKey,
        [string]$AdminPassword,
        [string]$ProjectName = "famas"
    )

    $configDir = Get-FaMASProjectConfigRoot -ProjectName $ProjectName
    $configPath = Get-FaMASProjectConfigPath -ProjectName $ProjectName
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    $payload = [ordered]@{
        project_name = $ProjectName
        FAMAS_SECRET_KEY = $SecretKey
        FAMAS_ADMIN_PASSWORD = $AdminPassword
        updated_at = (Get-Date).ToString("o")
    }
    $payload | ConvertTo-Json -Depth 4 | Set-Content -Path $configPath -Encoding UTF8
}

function Read-FaMASRequiredValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,
        [string]$DefaultValue = ""
    )

    while ($true) {
        $value = Read-Host $Prompt
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
        if ($DefaultValue) {
            return $DefaultValue
        }
    }
}

function Resolve-FaMASLocalSecrets {
    param(
        [string]$ProjectName = "famas",
        [string]$SecretKey = "",
        [string]$AdminPassword = ""
    )

    $saved = Read-FaMASProjectConfig -ProjectName $ProjectName
    if (-not $SecretKey) {
        $SecretKey = $saved.SecretKey
    }
    if (-not $AdminPassword) {
        $AdminPassword = $saved.AdminPassword
    }
    if (-not $SecretKey) {
        $SecretKey = Read-FaMASRequiredValue -Prompt "请输入 FAMAS_SECRET_KEY"
    }
    if (-not $AdminPassword) {
        $AdminPassword = Read-FaMASRequiredValue -Prompt "请输入 FAMAS_ADMIN_PASSWORD"
    }
    Save-FaMASProjectConfig -SecretKey $SecretKey -AdminPassword $AdminPassword -ProjectName $ProjectName
    return [pscustomobject]@{
        SecretKey = $SecretKey
        AdminPassword = $AdminPassword
        Path = Get-FaMASProjectConfigPath -ProjectName $ProjectName
    }
}
