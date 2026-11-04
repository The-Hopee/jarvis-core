@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
set "jarvis_exit=%ERRORLEVEL%"
pause
exit /b %jarvis_exit%
