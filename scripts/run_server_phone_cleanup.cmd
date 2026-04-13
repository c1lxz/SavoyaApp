@echo off
setlocal
powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_server_phone_cleanup.ps1" %*
exit /b %ERRORLEVEL%
