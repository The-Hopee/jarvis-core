param([switch]$SkipModel, [switch]$LocalVoice)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    & '.\.venv\Scripts\python.exe' -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'VK browser installation failed.' }
    cmake -S . -B build -G 'Visual Studio 17 2022' -A x64
    if ($LASTEXITCODE -ne 0) { throw 'CMake configuration failed.' }
    cmake --build build --config Release --parallel 6
    if ($LASTEXITCODE -ne 0) { throw 'Native build failed.' }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    if (-not $SkipModel) {
        & '.\.venv\Scripts\python.exe' -m jarvis --download-model
        if ($LASTEXITCODE -ne 0) { throw 'ASR model download failed.' }
    }
    if ($LocalVoice) {
        & (Join-Path $PSScriptRoot 'setup-voice.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Local voice setup failed.' }
    }
    & '.\.venv\Scripts\python.exe' -m jarvis --doctor
    if ($LASTEXITCODE -ne 0) { throw 'Installation check failed.' }
} finally { Pop-Location }
