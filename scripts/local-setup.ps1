param(
    [ValidateSet('qwen3:1.7b', 'qwen3:4b', 'qwen3:8b', 'qwen3:14b')]
    [string] $Model = 'qwen3:1.7b',
    [string] $Python,
    [switch] $SkipChromium
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw 'Setup command failed. See the output above.' } }
if (!(Test-Path '.venv314\Scripts\python.exe')) {
    if ($Python) { & $Python -m venv .venv314 }
    elseif (Get-Command python3.14.exe -ErrorAction SilentlyContinue) { python3.14.exe -m venv .venv314 }
    else { py -3.14 -m venv .venv314 }
    Check-Exit
}
$venvPython = '.\.venv314\Scripts\python.exe'
& $venvPython -m pip install 'torch==2.10.0+cpu' --index-url https://download.pytorch.org/whl/cpu
Check-Exit
& $venvPython -m pip install -r requirements-local.txt
Check-Exit
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD 'data\local\browsers'
if (!$SkipChromium) {
    & $venvPython -m playwright install chromium
    Check-Exit
}
$env:HF_HUB_DISABLE_TELEMETRY = '1'
& $venvPython scripts/download-local-embeddings.py
Check-Exit
. .\scripts\local-daemon.ps1
$daemon = Start-SellbirdOllama
try {
    & $daemon.Exe pull $Model
    Check-Exit
} finally {
    if (!$daemon.Process.HasExited) { Stop-Process -Id $daemon.Process.Id }
}
