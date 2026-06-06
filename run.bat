@echo off
chcp 65001 > nul
echo Перевірка системного середовища...

:: 1. Перевірка наявності Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ПОМИЛКА] Python не встановлено або не додано до змінних середовища PATH!
    echo Будь ласка, встановіть Python із сайту python.org
    pause
    exit /b 1
)

:: 2. Перевірка наявності бібліотек
python -c "import PIL, pillow_heif" >nul 2>nul
if %errorlevel% neq 0 (
    echo [ІНФО] Необхідні бібліотеки (Pillow, pillow-heif) відсутні.
    echo Запуск автоматичного встановлення залежностей через pip...
    python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ПОМИЛКА] Не вдалося встановити залежності. Перевірте з'єднання з інтернетом.
        pause
        exit /b 1
    )
) else (
    echo [УСПІХ] Всі необхідні бібліотеки вже встановлено!
)

:: 3. Запуск програми
echo Запуск програми PhotoCheckDate...
start "" python main.py
