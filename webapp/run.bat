@echo off
REM Start the web app. Activate your virtual environment first (see README),
REM or make sure `python` on PATH has the dependencies installed.
cd /d "%~dp0"
python manage.py migrate
echo.
echo Open http://localhost:8000  (Ctrl+C to stop)
python manage.py runserver
