param(
    [ValidateRange(1024, 65525)]
    [int]$Port = 5000,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python is missing: $python. Install the runtime dependencies first."
}

$configuration = Join-Path $root '.env'
if (Test-Path -LiteralPath $configuration) {
    $settings = Get-Content -LiteralPath $configuration -Raw
    if ($settings -match '(?m)^\s*QWEN_API_BASE\s*=\s*http://127\.0\.0\.1:11435/v1\s*$') {
        & (Join-Path $PSScriptRoot 'start_local_gpu.ps1') -Port 11435
    }
}

function Test-DemoHealth([int]$Candidate) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Candidate/health" -TimeoutSec 2
        return $health.status -eq 'ok' -and $health.revision -eq 'workbench-v5' -and $health.evaluation_revision -eq 'manual-evaluation-v2' -and $health.assistance_revision -eq 'compact-v9-item-issues-2'
    } catch {
        return $false
    }
}

function Test-PortBusy([int]$Candidate) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.ConnectAsync('127.0.0.1', $Candidate)
        return $connection.Wait(500) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

$selectedPort = $null
foreach ($candidate in $Port..($Port + 10)) {
    if (Test-DemoHealth $candidate) {
        $selectedPort = $candidate
        Write-Output "Existing demo is healthy on port $candidate."
        break
    }
    if (Test-PortBusy $candidate) {
        continue
    }
    $logs = Join-Path $root 'logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $logs "demo-$candidate-$stamp.out.log"
    $stderr = Join-Path $logs "demo-$candidate-$stamp.err.log"
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUNBUFFERED = '1'
    $process = Start-Process -FilePath $python `
        -ArgumentList @('-u', 'scripts/run_demo.py', '--port', "$candidate") `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardInput (Join-Path $PSScriptRoot 'empty.stdin') `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) {
            $details = Get-Content -LiteralPath $stderr -Tail 20 -ErrorAction SilentlyContinue
            throw "Demo exited during startup. Log: $stderr`n$($details -join [Environment]::NewLine)"
        }
        if (Test-DemoHealth $candidate) {
            $selectedPort = $candidate
            Write-Output "Demo started in background. PID: $($process.Id). Logs: $logs"
            break
        }
    }
    if ($null -eq $selectedPort) {
        throw "Demo startup timed out. Check $stderr. Child PID: $($process.Id)"
    }
    break
}
if ($null -eq $selectedPort) {
    throw 'No free port was found. Existing services were left unchanged.'
}

$base = "http://127.0.0.1:$selectedPort"
foreach ($page in @('/workbench', '/dashboard', '/evaluation')) {
    $response = Invoke-WebRequest -Uri "$base$page" -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -ne 200) {
        throw "Page check failed: $base$page"
    }
    Write-Output "Ready: $base$page"
}
if ($OpenBrowser) {
    Start-Process "$base/workbench"
}
