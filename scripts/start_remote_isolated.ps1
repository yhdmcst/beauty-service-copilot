param(
    [string]$HostAlias = 'amax-server',
    [ValidateRange(1024, 65535)]
    [int]$LocalPort = 11438
)

$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Beauty Copilot - Isolated Remote GPU'
Write-Host 'Enter the SSH password here. This starts a separate user-owned runtime on remote port 11437.'
Write-Host 'Existing Ollama processes are left running. Check remote process state after closing this window.'
$remote = 'set -eu; echo READABLE_MODEL_DIRECTORIES; modeldir=""; for d in "$HOME/.ollama/models" /usr/share/ollama/.ollama/models; do if test -r "$d/manifests"; then echo "$d"; modeldir="$d"; break; fi; done; if test -z "$modeldir"; then echo NO_READABLE_MODEL_DIRECTORY; exit 4; fi; echo BACKEND_FILES; find /usr/local/lib/ollama -maxdepth 2 -type f -name "*cuda*" 2>/dev/null | head -n 8; if ss -ltn | grep -q "127.0.0.1:11437"; then echo ISOLATED_PORT_BUSY; exit 5; fi; export OLLAMA_MODELS="$modeldir" OLLAMA_HOST=127.0.0.1:11437 CUDA_VISIBLE_DEVICES=3; exec /usr/local/bin/ollama serve'
& ssh.exe -T -o ConnectTimeout=15 -o StrictHostKeyChecking=yes `
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o NumberOfPasswordPrompts=1 `
    -L "127.0.0.1:${LocalPort}:127.0.0.1:11437" $HostAlias $remote
Write-Host "Isolated session closed. Exit code: $LASTEXITCODE"
