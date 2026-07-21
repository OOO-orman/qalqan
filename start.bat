@echo off
cd /d "%~dp0backend"

if not exist venv (
    echo Setup has not been run yet.
    echo Please run setup.bat first.
    pause
    exit /b 1
)

echo Starting Qalqan...
start "Qalqan Server - do not close this window" cmd /k "call venv\Scripts\activate.bat && uvicorn main:app --port 8000"

echo Waiting for the server to start...
timeout /t 4 /nobreak >nul

echo Opening dashboard in your browser...
start "" http://127.0.0.1:8000

echo.
echo Done! The dashboard should now be open in your browser.
echo Keep the "Qalqan Server" window open while you use the system.
echo This window can be closed.
timeout /t 3 >nul
