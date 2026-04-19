@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
title Savoya Launcher

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\restart_production_workspace.ps1" -RepoRoot "%ROOT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo(
if not "%EXIT_CODE%"=="0" (
    echo Launch failed. Check the log above.
) else (
    echo Done. Savoya backend, web build and nginx were restarted.
)
pause
exit /b %EXIT_CODE%
