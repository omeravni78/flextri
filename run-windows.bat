@echo off
rem flexTri from a checkout, for developers. Everyone else: install flexTri from the GitHub Releases page.
rem Double-click this file, or run it from a Command Prompt in this folder.
rem First run sets up a .venv folder (needs Python 3.12+ from python.org; 3.11 runs but can't log in to Garmin). Every run makes sure the
rem dependencies match pyproject.toml, so a .venv made from an older checkout gets what it is missing.
setlocal
cd /d "%~dp0"

rem Garmin's login keeps changing and the Garmin library's current releases need Python 3.12+. A .venv on an
rem older Python is rebuilt on the newest Python installed; it holds nothing but installed packages.
set "NEWPY="
for %%v in (3.14 3.13 3.12) do if not defined NEWPY py -%%v -c "" >nul 2>&1 && set "NEWPY=py -%%v"
if exist ".venv\Scripts\python.exe" if defined NEWPY (
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 12))" || (
        echo Moving flexTri to a newer Python so Garmin login works...
        rmdir /s /q .venv
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Setting up flexTri the first time...
    if defined NEWPY (
        %NEWPY% -m venv .venv
    ) else (
        py -3 -m venv .venv || python -m venv .venv
    )
    if not exist ".venv\Scripts\python.exe" goto :nopython
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)

echo Checking dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -e ".[dev,garmin,app]" || goto :failed

echo Starting flexTri; it opens in your browser. Close this window or press Quit in the app to stop it.
".venv\Scripts\python.exe" -m flextri.launcher
goto :eof

:nopython
echo Python was not found. Install Python 3.12 or newer from https://www.python.org/downloads/windows/
echo and tick "Add python.exe to PATH" during setup, then run this file again.
pause
exit /b 1

:failed
echo Installing flexTri failed. Scroll up for the error.
pause
exit /b 1
