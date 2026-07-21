@echo off
echo ===============================================
echo   Qalqan - First-time setup
echo ===============================================
echo.

cd /d "%~dp0backend"

if not exist venv (
    echo Creating virtual environment...
    py -3.12 -m venv venv
    if errorlevel 1 (
        echo.
        echo ERROR: could not create venv using "py -3.12".
        echo Make sure Python 3.12 is installed ^(python.org/downloads,
        echo version 3.12.x - NOT 3.13/3.14, see README^).
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo Installing dependencies, this may take a minute...
pip install -r requirements.txt

if not exist .env (
    echo.
    echo Creating .env from template...
    copy .env.example .env >nul
    echo.
    echo Notepad will open now - fill in your keys there
    echo ^(Gemini/OpenAI, Telegram API_ID/HASH, phone number, ADMIN_TELEGRAM_USERNAME^)
    echo then SAVE the file ^(Ctrl+S^) and close Notepad.
    pause
    notepad .env
) else (
    echo.
    echo .env already exists - skipping.
)

echo.
echo ===============================================
echo   Setup complete!
echo   Now run start.bat to launch Qalqan.
echo ===============================================
pause
