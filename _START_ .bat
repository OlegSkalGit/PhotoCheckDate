@echo off
cd /d "%~dp0"
chcp 1251 > nul

setlocal enabledelayedexpansion

title TemplateMachine Control Center
echo ========================================================
echo  TEMPLATEMACHINE CONTROL CENTER
echo ========================================================
echo.

REM 1. Перевірка наявності Python
python --version >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Python НЕ знайдено у системі.
    if not exist "setup\python-3.12.10-amd64.exe" (
        echo Інсталятор Python не знайдено. Завантажуємо...
        if not exist "setup" mkdir "setup"
        curl -L "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -o "setup\python-3.12.10-amd64.exe"
        if !ERRORLEVEL! neq 0 (
            echo.
            echo ===============================================================================================
            echo Для ПЕРШОГО запуску програми необхідний інтернет для завантаження ДОДАТКОВИХ компонентів.
            echo ===============================================================================================
            echo.
            echo Не вдалося завантажити Python. Перевірте з'єднання з інтернетом.
            pause
            exit /b 1
        )
    ) else (
        echo Інсталятор Python знайдено. Встановлюємо...
        .\setup\python-3.12.10-amd64.exe /quiet PrependPath=1 InstallAllUsers=1
        if !ERRORLEVEL! neq 0 (
            echo.
            echo ===============================================================================================
            echo Для ПЕРШОГО запуску програми необхідний інтернет для завантаження ДОДАТКОВИХ компонентів.
            echo ===============================================================================================
            echo.
            echo Не вдалося встановити Python. Перевірте з'єднання з інтернетом.
            pause
            exit /b 1
        ) else (
            echo Очікування завершення встановлення...
            timeout /t 15 > nul
        )
    )
) else (
   echo Python знайдено у системі.
)

REM 2. Створення віртуального оточення
if not exist ".venv" (
    echo Віртуальне оточення Python .venv у проекті відсутнє. Створюємо...
    echo.
    python -m venv .venv
) else (
    echo Віртуальне оточення Python .venv у проекті знайдено.
)

REM 3. Перевірка наявності необхідних бібліотек
.venv\Scripts\python.exe -c "import PIL, pillow_heif" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Необхідні бібліотеки Python НЕ знайдено у проекті. Завантажуємо і встановлюємо...
    .venv\Scripts\pip install -r requirements.txt
    if !ERRORLEVEL! == 1 (
        echo.
        echo ===============================================================================================
        echo Для ПЕРШОГО запуску програми необхідний інтернет для завантаження ДОДАТКОВИХ компонентів.
        echo ===============================================================================================
        echo.
        echo [Помилка] Не вдалося встановити бібліотеки. Перевірте з'єднання з інтернетом.
        pause
        exit /b 1
    )
) else (
    echo Необхідні бібліотеки Python знайдено у проекті.
)

endlocal

REM 5. Запуск Streamlit
echo.
echo Все готово до запуску!
echo Запуск додатку...
echo.
rem start ".venv\Scripts\python" "main.py"
".venv\Scripts\python" "main.py"
pause