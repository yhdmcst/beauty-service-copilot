param(
    [string]$HostAlias = 'amax-server',
    [ValidateRange(1024, 65535)]
    [int]$LocalPort = 11436
)

$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Beauty Copilot - Remote Model SSH'
Clear-Host
Write-Host 'Enter the SSH password here. The password is hidden and is not stored.'
Write-Host "Forwarding localhost:$LocalPort to the remote Ollama service."
Write-Host 'Leave this window open during remote model evaluation. Ctrl+C closes only this tunnel.'
& ssh.exe -N -T -o ConnectTimeout=15 -o StrictHostKeyChecking=yes `
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 `
    -o NumberOfPasswordPrompts=1 -L "127.0.0.1:${LocalPort}:127.0.0.1:11434" $HostAlias
if ($LASTEXITCODE -ne 0) { Write-Host "Tunnel closed with code $LASTEXITCODE." }
