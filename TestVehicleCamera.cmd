@echo off
setlocal

set "ROOT=%~dp0"
pushd "%ROOT%" >nul

if "%~1"=="" (
    set /p VEHICLE_NUMBER=Vehicle number: 
) else (
    set "VEHICLE_NUMBER=%~1"
)

if not defined VEHICLE_NUMBER (
    echo Vehicle number is required.
    popd >nul
    exit /b 1
)

if "%~2"=="" (
    set "ACTION=entry"
) else (
    set "ACTION=%~2"
)

py -3.12 backend\app\scripts\simulate_vehicle_camera.py --vehicle-number "%VEHICLE_NUMBER%" --action "%ACTION%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
pause
popd >nul
exit /b %EXIT_CODE%
