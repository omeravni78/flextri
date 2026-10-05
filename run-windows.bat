@echo off
rem flexTri on Windows: double-click this file, or run it from a Command Prompt in this folder.
rem First run sets up a .venv folder (needs Python 3.11+ from python.org). Every run makes sure the
rem dependencies match pyproject.toml, so a .venv made from an older checkout gets what it is missing.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up flexTri the first time...
    py -3 -m venv .venv || python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)

echo Checking dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -e ".[dev,garmin]" || goto :failed

echo Starting flexTri at http://127.0.0.1:8000  (close this window to stop it)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn flextri.web.api:app --port 8000
goto :eof

:nopython
echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/windows/
echo and tick "Add python.exe to PATH" during setup, then run this file again.
pause
exit /b 1

:failed
echo Installing flexTri failed. Scroll up for the error.
pause
exit /b 1
