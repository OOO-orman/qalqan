@echo off
chcp 65001 >nul
cd /d "%~dp0backend"

if not exist venv (
    echo Похоже, первоначальная настройка ещё не выполнена.
    echo Сначала запустите setup.bat
    pause
    exit /b 1
)

echo Запускаю Qalqan...
start "Qalqan Server (не закрывайте это окно)" cmd /k "call venv\Scripts\activate.bat && uvicorn main:app --port 8000"

echo Жду запуск сервера...
timeout /t 4 /nobreak >nul

echo Открываю дашборд в браузере...
start "" http://127.0.0.1:8000

echo.
echo Готово! Дашборд открыт в браузере.
echo Окно "Qalqan Server" должно оставаться открытым, пока вы пользуетесь системой.
echo Это окно можно закрыть.
timeout /t 3 >nul
