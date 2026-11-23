# Dot-source from the repository root.
function Start-SellbirdOllama {
    $command = Get-Command ollama.exe -ErrorAction SilentlyContinue
    $executable = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if ($command) { $executable = $command.Source }
    if (!(Test-Path -LiteralPath $executable)) {
        throw 'Install the official Ollama for Windows package first.'
    }

    $env:OLLAMA_HOST = '127.0.0.1:11435'
    $env:OLLAMA_NO_CLOUD = '1'
    $env:OLLAMA_VULKAN = '0'
    $env:OLLAMA_DISABLE_UPDATES = '1'
    $env:OLLAMA_MODELS = Join-Path $PWD 'data\local\ollama'
    $env:OLLAMA_NUM_PARALLEL = '1'
    $env:OLLAMA_MAX_LOADED_MODELS = '1'
    if ($env:SELLBIRD_LOCAL_CPU_ONLY -eq '1') {
        $env:CUDA_VISIBLE_DEVICES = '-1'
        $env:ROCR_VISIBLE_DEVICES = '-1'
    }
    New-Item -ItemType Directory -Force 'data\local' | Out-Null
    $probe = [System.Net.Sockets.TcpClient]::new()
    try {
        $probe.Connect('127.0.0.1', 11435)
        throw 'Port 11435 is already in use. Stop the existing assignment daemon first.'
    } catch [System.Net.Sockets.SocketException] {
        # The loopback port is free.
    } finally {
        $probe.Dispose()
    }

    $log = Join-Path $PWD 'data\local\ollama.log'
    $proc = Start-Process -FilePath $executable -ArgumentList 'serve' -PassThru -WindowStyle Hidden -RedirectStandardError $log
    try {
        for ($attempt = 0; $attempt -lt 80; $attempt++) {
            if ($proc.HasExited) { throw "Ollama exited. Check $log." }
            $cloudDisabled = (Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue) -match 'cloud disabled.*true'
            if ($cloudDisabled) {
                try {
                    curl.exe -fsS --noproxy '*' --max-time 1 "http://$env:OLLAMA_HOST/api/version" -o NUL 2>$null
                    if ($LASTEXITCODE -eq 0) { return @{ Process = $proc; Exe = $executable } }
                } catch {}
            }
            Start-Sleep -Milliseconds 500
        }
        throw "Could not verify local-only Ollama startup. Check $log."
    } catch {
        if (!$proc.HasExited) { Stop-Process -Id $proc.Id }
        throw
    }
}
