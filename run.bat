@echo off
setlocal
cd /d "%~dp0"

title Douyin Workspace
echo Restarting Douyin workspace services...
echo Stopping previous gateway and tab services...

rem Clear listeners from the previous run so updated source files are loaded.
for %%P in (8003 8101 8102 8103) do (
    for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
        taskkill /PID %%I /T /F >nul 2>&1
    )
)
timeout /t 1 /nobreak >nul

echo Starting the gateway and tab services...
echo Open http://127.0.0.1:8003/ or http://192.168.3.104:8003/
echo Keep this window open while using the services.
echo.

python web_app.py --host 0.0.0.0 --port 8003 --service-host 0.0.0.0

if errorlevel 1 (
    echo.
    echo Service startup failed. Check that Python is installed and available on PATH.
    pause
)
endlocal
