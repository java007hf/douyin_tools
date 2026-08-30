@echo off
setlocal
cd /d "%~dp0"

echo Starting Douyin workspace services...
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
