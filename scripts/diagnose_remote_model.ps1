param(
    [string]$HostAlias = 'amax-server'
)

$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Beauty Copilot - Remote Model Diagnostics'
$root = Split-Path -Parent $PSScriptRoot
$directory = Join-Path $root 'archive\remote_gpu_checks'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$report = Join-Path $directory "diagnostics-$stamp.txt"
$remote = 'echo GPU; nvidia-smi --query-gpu=index,name,memory.free,utilization.gpu --format=csv,noheader; echo MODEL_PROCESSES; ps -eo pid,comm,pcpu,pmem | awk ''$2 ~ /ollama|llama/ {print}''; echo PROCESS_BINARIES; for p in $(pgrep -x ollama); do echo PID=$p; readlink /proc/$p/exe; done; echo RUNTIME; command -v ollama; ollama --version; echo LIBRARY_PATHS; ls -ld /usr/local/lib/ollama /usr/lib/ollama 2>/dev/null; echo SYSTEM; uname -m; echo AVAILABLE_RUNTIME_LOGS; for p in /tmp/ollama.log /tmp/ollama-server.log; do if test -r "$p"; then tail -n 30 "$p"; fi; done'
Write-Host 'Enter the SSH password here. Only runtime diagnostics will be collected.'
& ssh.exe -o ConnectTimeout=15 -o StrictHostKeyChecking=yes -o NumberOfPasswordPrompts=1 `
    $HostAlias $remote | Tee-Object -FilePath $report
Write-Host "Diagnostic report: $report. Exit code: $LASTEXITCODE"
