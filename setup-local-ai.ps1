param()
$ErrorActionPreference = 'Stop'
$localAssistantRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Jarvis'
$localAssistantPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$localVoiceRoot = Join-Path $localAssistantRoot 'runtimes\qwen-tts'
$localVoicePython = Join-Path $localVoiceRoot 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $localAssistantPython)) { throw 'Run the normal source setup first.' }
& $localAssistantPython -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,13) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'The pinned local voice environment requires Python 3.13 x64.' }
$localNvidiaCommand = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $localNvidiaCommand) { throw 'This voice setup requires an NVIDIA CUDA GPU. The basic assistant still works without it.' }
$localGpuCapabilities = & $localNvidiaCommand.Source --query-gpu=compute_cap --format=csv,noheader
if ($LASTEXITCODE -ne 0) { throw 'Cannot check BF16 GPU capability.' }
$localHasBf16 = @($localGpuCapabilities | Where-Object { [double]::Parse($_.Trim(),[Globalization.CultureInfo]::InvariantCulture) -ge 8.0 }).Count -gt 0
if (-not $localHasBf16) { throw 'This voice runtime requires a BF16-capable NVIDIA GPU (RTX 30 or newer). Use the basic local Windows voice otherwise.' }
if (-not (Test-Path -LiteralPath $localVoicePython)) {
    & $localAssistantPython -m venv $localVoiceRoot
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create isolated voice environment.' }
}
& $localVoicePython -m pip install torch==2.9.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu130
if ($LASTEXITCODE -ne 0) { throw 'CUDA runtime installation failed.' }
& $localVoicePython -m pip install -r (Join-Path $PSScriptRoot 'requirements-local-voice.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Voice dependencies installation failed.' }
& $localAssistantPython (Join-Path $PSScriptRoot 'scripts\setup_private_models.py')
if ($LASTEXITCODE -ne 0) { throw 'Local model installation failed.' }
Write-Output 'Local models installed. Configure local-ai.json using docs/LOCAL_AI.md before enabling.'
