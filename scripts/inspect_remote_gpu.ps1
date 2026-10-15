param(
    [string]$HostAlias = 'amax-server'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$directory = Join-Path $root 'archive\remote_gpu_checks'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$report = Join-Path $directory "inventory-$stamp.txt"
$status = Join-Path $directory "status-$stamp.json"
$remote = 'nvidia-smi --query-gpu=index,name,memory.total,memory.free,utilization.gpu --format=csv,noheader; printf "\nRUNTIMES\n"; command -v ollama || true; command -v python3 || true; command -v vllm || true; printf "\nLOCAL_MODEL_PORTS\n"; ss -ltn 2>/dev/null | awk ''$4 ~ /:(11434|8000|8001)$/ {print $4}'''

Write-Host 'Enter the SSH password in this window. SSH hides the password; it is not saved.'
Write-Host 'Only GPU inventory, runtime availability and model listening ports will be checked.'
& ssh.exe -o ConnectTimeout=15 -o StrictHostKeyChecking=yes -o NumberOfPasswordPrompts=1 $HostAlias $remote |
    Tee-Object -FilePath $report
$result = $LASTEXITCODE
[ordered]@{
    checked_at = (Get-Date).ToString('o')
    host_alias = $HostAlias
    exit_code = $result
    report = [IO.Path]::GetFileName($report)
    scope = 'Read-only remote inventory; no installation, model job or credential persistence.'
} | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding utf8
Write-Host "Inspection finished. Exit code: $result. Report: $report"
