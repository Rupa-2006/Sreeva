@echo off
title Sreeva - keep this window open while using the website
cd /d "%~dp0"
rem development mode on this computer (the live website runs with DEBUG off)
set DJANGO_DEBUG=1

echo.
echo  ==========================================
echo    Starting Sreeva...
echo  ==========================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo  First time setup: creating the Python environment. This takes a minute...
    python -m venv venv || py -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

echo  Saving a backup copy of your data...
python manage.py backup
echo  Updating the database (safe to run every time)...
python manage.py migrate
if errorlevel 1 (
    echo.
    echo  Something went wrong. Copy the red text above to find the problem.
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo    Sreeva is running at:
echo        http://127.0.0.1:8000
echo.
echo    KEEP THIS WINDOW OPEN while you use the website.
echo    To stop it: close this window, or press Ctrl+C.
echo  ==========================================
echo.

rem Open the website in the browser after 3 seconds
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"

python manage.py runserver
pause
