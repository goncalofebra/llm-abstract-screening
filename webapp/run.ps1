# Start the web app. Activate your virtual environment first (see README),
# or make sure `python` on PATH has the dependencies installed.
Set-Location -Path $PSScriptRoot
python manage.py migrate
Write-Host ""
Write-Host "Open http://localhost:8000  (Ctrl+C to stop)"
python manage.py runserver
