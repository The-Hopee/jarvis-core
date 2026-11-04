param([Parameter(Position=0)][ValidateSet('status','start','stop','restart','foreground','logs')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$jarvisTaskName = 'Jarvis-HomeAssistant'
$jarvisDescription = 'Jarvis home voice assistant; interactive user logon and restart on failure.'
$jarvisPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$jarvisGuiPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$jarvisLog = Join-Path $env:LOCALAPPDATA 'Jarvis\logs\assistant.log'
if (-not (Test-Path -LiteralPath $jarvisPython)) { throw 'Run setup.ps1 first.' }
$jarvisTask = Get-ScheduledTask -TaskName $jarvisTaskName -ErrorAction SilentlyContinue
if ($jarvisTask -and ($jarvisTask.Description -ne $jarvisDescription -or $jarvisTask.Actions.Execute -ne $jarvisGuiPython)) {
    throw 'An unrelated task uses the Jarvis task name.'
}
function Stop-JarvisInstance {
    & $jarvisPython -m jarvis.control stop --timeout 60
    if ($LASTEXITCODE -ne 0) { throw 'Graceful stop is still pending; retry after the current command completes.' }
    $jarvisStopDeadline = (Get-Date).AddSeconds(10)
    while ($jarvisTask -and (Get-ScheduledTask -TaskName $jarvisTaskName).State -eq 'Running') {
        if ((Get-Date) -gt $jarvisStopDeadline) { throw 'Task is still stopping. Retry in a few seconds.' }
        Start-Sleep -Milliseconds 100
    }
}
function Start-JarvisInstance {
    if (-not $jarvisTask) { throw 'Run install-autostart.ps1 first.' }
    if ($jarvisTask.State -eq 'Disabled') { throw 'The task is disabled. Reinstall autostart to enable it.' }
    Start-ScheduledTask -TaskName $jarvisTaskName
    & $jarvisPython -m jarvis.control wait-running --timeout 15
    if ($LASTEXITCODE -ne 0) { throw 'Jarvis did not start. Check manage.cmd logs.' }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    switch ($Action) {
        'status' {
            if ($jarvisTask) { $jarvisTask | Select-Object TaskName, State }
            else { Write-Output 'Autostart is not registered.' }
            & $jarvisPython -m jarvis.control status
        }
        'start' { Start-JarvisInstance }
        'stop' { Stop-JarvisInstance }
        'restart' { Stop-JarvisInstance; Start-JarvisInstance }
        'foreground' {
            Stop-JarvisInstance
            & $jarvisPython -m jarvis
            exit $LASTEXITCODE
        }
        'logs' {
            if (Test-Path -LiteralPath $jarvisLog) { Get-Content -Encoding UTF8 -LiteralPath $jarvisLog -Tail 60 }
            else { Write-Output ('No log yet: ' + $jarvisLog) }
        }
    }
} finally { Pop-Location }
