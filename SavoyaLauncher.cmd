@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "DOMAIN=ipksavoya.ru"
set "WWW_DOMAIN=www.ipksavoya.ru"
set "PUBLIC_IP=185.245.187.125"
set "LOCAL_HOSTS_IP=127.0.0.1"
set "NO_PROXY_LIST=%DOMAIN%,%WWW_DOMAIN%,127.0.0.1,localhost,::1"
title Savoya Launcher

>nul 2>&1 "%SystemRoot%\System32\fltmc.exe"
if not "%ERRORLEVEL%"=="0" (
    echo Requesting administrator rights to apply network fix and restart nginx...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%ROOT%' -Verb RunAs"
    exit /b 0
)

set "NO_PROXY=%NO_PROXY_LIST%"
set "no_proxy=%NO_PROXY_LIST%"

echo Applying local domain and proxy bypass fix...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\fix_server_domain_access.ps1" -Domain "%DOMAIN%" -WwwDomain "%WWW_DOMAIN%" -HostsIp "%LOCAL_HOSTS_IP%"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo Network fix failed. Check the log above.
    pause
    exit /b %EXIT_CODE%
)

echo Restarting Savoya production workspace...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\restart_production_workspace.ps1" -RepoRoot "%ROOT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo(
if not "%EXIT_CODE%"=="0" (
    echo Launch failed. Check the log above.
) else (
    echo Done. Domain fix, backend, web build and nginx were restarted.
)
pause
exit /b %EXIT_CODE%
