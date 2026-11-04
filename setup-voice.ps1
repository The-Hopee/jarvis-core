$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements-voice.lock.txt --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install CPU speech runtime.' }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install speech model dependencies.' }
    & '.\.venv\Scripts\python.exe' -m jarvis --download-voice
    if ($LASTEXITCODE -ne 0) { throw 'Cannot download the local voice model.' }
} finally { Pop-Location }
