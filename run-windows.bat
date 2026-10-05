@echo off
rem flexTri from a checkout, for developers. Everyone else: install flexTri from the GitHub Releases page.
rem Double-click this file, or run it from a Command Prompt in this folder.
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
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -e ".[dev,garmin,app]" || goto :failed

echo Starting flexTri; it opens in your browser. Close this window or press Quit in the app to stop it.
".venv\Scripts\python.exe" -m flextri.launcher
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
