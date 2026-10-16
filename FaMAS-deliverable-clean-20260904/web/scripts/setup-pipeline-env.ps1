param(
    [string]$Python = "python",
    [switch]$GpuTorch
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$PipelineDir = Join-Path $ProjectRoot "code_implement"
$VenvDir = Join-Path $PipelineDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RootRequirements = Join-Path $ProjectRoot "requirements.txt"

if (-not (Test-Path $VenvPython)) {
    & $Python -m venv $VenvDir
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $RootRequirements
if ($GpuTorch) {
    & $VenvPython -m pip install --upgrade --force-reinstall `
        torch==2.6.0+cu124 `
        torchvision==0.21.0+cu124 `
        torchaudio==2.6.0+cu124 `
        --index-url https://download.pytorch.org/whl/cu124
}

Write-Host "FaMAS pipeline environment ready: $VenvPython"
Write-Host "Next check:"
Write-Host "  $VenvPython -c `"import mineru; print('MinerU import OK')`""
Write-Host "  $VenvPython -c `"import torch; print(torch.__version__, torch.cuda.is_available())`""
