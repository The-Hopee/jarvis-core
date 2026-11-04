param([switch]$Text, [switch]$Mute, [string]$Command)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$pythonPath = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup.ps1 first.' }
Push-Location -LiteralPath $taskRoot
try {
    $arguments = @('-m', 'jarvis')
    if ($Text) { $arguments += '--text' }
    if ($Mute) { $arguments += '--mute' }
    if ($Command) { $arguments += @('--once', $Command) }
    & $pythonPath @arguments
    $resultCode = $LASTEXITCODE
} finally { Pop-Location }
exit $resultCode
