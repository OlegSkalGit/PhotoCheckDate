@echo off
chcp 65001 > nul
echo Перевірка середовища...

".venv\Scripts\python" -c "import PIL, pillow_heif" >nul 2>nul
if %errorlevel% neq 0 (
    echo [ІНФО] Встановлення залежностей у віртуальне середовище...
    ".venv\Scripts\pip" install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ПОМИЛКА] Не вдалося встановити бібліотеки.
        pause
        exit /b 1
    )
)

start "" ".venv\Scripts\pythonw" "main.py"
exit
