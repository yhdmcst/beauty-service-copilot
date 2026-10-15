param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 11435,
    [string]$Runtime = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Runtime) { $Runtime = $env:OLLAMA_GPU_RUNTIME }
if (-not $Runtime) {
    $Runtime = Join-Path $root 'archive\emotion_gpu_20261013\vulkan-portable'
}
$exe = Join-Path $Runtime 'ollama.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    throw 'A complete local GPU runtime is required. Set OLLAMA_GPU_RUNTIME to its directory.'
}
$base = "http://127.0.0.1:$Port"
try {
    $health = Invoke-RestMethod "$base/api/version" -TimeoutSec 2
    if ($health.version) {
        Write-Output "Existing Ollama endpoint: $base"
        Write-Output 'Check model allocation with scripts/check_local_model.py after loading.'
        exit 0
    }
} catch {}
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$env:OLLAMA_HOST = "127.0.0.1:$Port"
$env:OLLAMA_VULKAN = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_CONTEXT_LENGTH = '4096'
$env:OLLAMA_MODELS = Join-Path $env:USERPROFILE '.ollama\models'
$process = Start-Process -FilePath $exe -ArgumentList @('serve') -WorkingDirectory $Runtime `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs "gpu-$stamp.out.log") `
    -RedirectStandardError (Join-Path $logs "gpu-$stamp.err.log")
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    $process.Refresh()
    if ($process.HasExited) { throw 'GPU runtime exited. Read its log.' }
    try {
        $health = Invoke-RestMethod "$base/api/version" -TimeoutSec 1
        if ($health.version) {
            Write-Output "Ollama ready: $base, PID $($process.Id)."
            Write-Output "Configure QWEN_API_BASE=$base/v1 in your private .env."
            exit 0
        }
    } catch {}
}
throw "Startup timed out. Child PID: $($process.Id); check logs."
