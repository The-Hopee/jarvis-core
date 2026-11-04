param([switch]$Uninstall, [switch]$StartNow)
$ErrorActionPreference = 'Stop'
$jarvisTaskName = 'Jarvis-HomeAssistant'
$jarvisDescription = 'Jarvis home voice assistant; interactive user logon and restart on failure.'
$jarvisPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$jarvisExisting = Get-ScheduledTask -TaskName $jarvisTaskName -ErrorAction SilentlyContinue
if ($jarvisExisting -and ($jarvisExisting.Description -ne $jarvisDescription -or $jarvisExisting.Actions.Execute -ne $jarvisPython)) {
    throw 'An unrelated task uses this name; refusing to replace or remove it.'
}
if ($Uninstall) {
    if ($jarvisExisting) { Unregister-ScheduledTask -TaskName $jarvisTaskName -Confirm:$false }
    Write-Output 'Jarvis autostart removed. Use manage.cmd stop to stop an existing process.'
    exit 0
}
foreach ($jarvisRequired in @($jarvisPython, (Join-Path $PSScriptRoot 'jarvis\background.py'), (Join-Path $PSScriptRoot 'build\bin\Release\jarvis-core.exe'))) {
    if (-not (Test-Path -LiteralPath $jarvisRequired)) { throw 'Complete setup.ps1 before enabling autostart.' }
}
$jarvisUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$jarvisAction = New-ScheduledTaskAction -Execute $jarvisPython -Argument '-m jarvis.background' -WorkingDirectory $PSScriptRoot
$jarvisTrigger = New-ScheduledTaskTrigger -AtLogOn -User $jarvisUser
$jarvisTrigger.Delay = 'PT10S'
$jarvisPrincipal = New-ScheduledTaskPrincipal -UserId $jarvisUser -LogonType Interactive -RunLevel Limited
$jarvisSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $jarvisTaskName -Description $jarvisDescription -Action $jarvisAction -Trigger $jarvisTrigger -Principal $jarvisPrincipal -Settings $jarvisSettings -Force | Out-Null
Write-Output 'Jarvis autostart enabled: 10 seconds after this user logs on, without a console window.'
if ($StartNow) {
    & (Join-Path $PSScriptRoot 'manage.ps1') -Action start
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Get-ScheduledTask -TaskName $jarvisTaskName | Select-Object TaskName, State
