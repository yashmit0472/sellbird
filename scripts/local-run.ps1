param([switch] $Offline, [switch] $CpuOnly)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD 'data\local\browsers'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:SELLBIRD_LOCAL_OLLAMA_PORT = '11435'
if ($Offline) {
    # Block the daemon's external HTTP clients at process scope while keeping loopback.
    $env:HTTP_PROXY = 'http://127.0.0.1:1'
    $env:HTTPS_PROXY = 'http://127.0.0.1:1'
    $env:NO_PROXY = 'localhost,127.0.0.1,::1'
}
. .\scripts\local-daemon.ps1
try {
    if ($CpuOnly) { $env:SELLBIRD_LOCAL_CPU_ONLY = '1' }
    $daemon = Start-SellbirdOllama
    $env:SELLBIRD_LOCAL_OLLAMA_UNVERIFIED = '0'
} catch {
    Write-Warning $_
    $env:SELLBIRD_LOCAL_OLLAMA_UNVERIFIED = '1'
    Write-Warning 'Starting the dashboard with inference paused. Restart the launcher once local Ollama is available.'
}
try {
    $appArgs = @('-m', 'sellbird.local')
    if ($Offline) { $appArgs += '--offline' }
    & .\.venv314\Scripts\python.exe @appArgs
} finally {
    if ($daemon -and !$daemon.Process.HasExited) { Stop-Process -Id $daemon.Process.Id }
}
