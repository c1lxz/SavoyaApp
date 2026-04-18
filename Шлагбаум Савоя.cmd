@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
title Шлагбаум Савоя

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\restart_production_workspace.ps1" -RepoRoot "%ROOT%"

echo.
if errorlevel 1 (
    echo Ошибка запуска. Проверьте текст выше.
) else (
    echo Готово. Savoya backend, web build и nginx обработаны.
)
pause
