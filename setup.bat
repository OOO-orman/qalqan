@echo off
chcp 65001 >nul
echo ===============================================
echo   Qalqan - первоначальная настройка
echo ===============================================
echo.

cd /d "%~dp0backend"

if not exist venv (
    echo Создаю виртуальное окружение...
    py -3.12 -m venv venv
    if errorlevel 1 (
        echo.
        echo ОШИБКА: не удалось создать venv через "py -3.12".
        echo Убедитесь, что установлен Python 3.12 (python.org/downloads,
        echo версия 3.12.x, НЕ 3.13/3.14 - см. README).
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo Устанавливаю библиотеки (может занять пару минут)...
pip install -r requirements.txt

if not exist .env (
    echo.
    echo Создаю файл .env из шаблона...
    copy .env.example .env >nul
    echo.
    echo Сейчас откроется .env в Блокноте - впишите туда ваши ключи
    echo ^(Gemini/OpenAI, Telegram API_ID/HASH, номер телефона, ADMIN_TELEGRAM_USERNAME^)
    echo и СОХРАНИТЕ файл ^(Ctrl+S^), затем закройте Блокнот.
    pause
    notepad .env
) else (
    echo.
    echo Файл .env уже существует - пропускаю.
)

echo.
echo ===============================================
echo   Настройка завершена!
echo   Теперь запускайте файл start.bat для работы.
echo ===============================================
pause
