#!/usr/bin/env bash
# flexTri from a checkout on Linux or macOS, for developers. The run-windows.bat of the other systems.
# Run it from this folder: ./run-linux.sh
# First run sets up a .venv folder (needs Python 3.12+; 3.11 runs but can't log in to Garmin). Every run makes sure
# the dependencies match pyproject.toml, so a .venv made from an older checkout gets what it is missing.
set -e
cd "$(dirname "$0")"

# Garmin's login keeps changing and the Garmin library's current releases need Python 3.12+. Pick the newest
# Python installed; a .venv on an older Python is rebuilt, since it holds nothing but installed packages.
NEWPY=""
for v in 3.14 3.13 3.12; do
    if command -v "python$v" >/dev/null 2>&1; then NEWPY="python$v"; break; fi
done
if [ -z "$NEWPY" ] && python3 -c "import sys; sys.exit(sys.version_info < (3, 12))" 2>/dev/null; then
    NEWPY=python3
fi
if [ -x .venv/bin/python ] && [ -n "$NEWPY" ] && ! .venv/bin/python -c "import sys; sys.exit(sys.version_info < (3, 12))"; then
    echo "Moving flexTri to a newer Python so Garmin login works..."
    rm -rf .venv
fi

if [ ! -x .venv/bin/python ]; then
    echo "Setting up flexTri the first time..."
    PY="${NEWPY:-python3}"
    if ! command -v "$PY" >/dev/null 2>&1; then
        echo "Python was not found. Install Python 3.12 or newer (Ubuntu: sudo apt install python3 python3-venv), then run this again."
        exit 1
    fi
    if ! "$PY" -m venv .venv; then
        rm -rf .venv
        echo "Creating the .venv failed. On Ubuntu install the venv module first: sudo apt install python3-venv"
        exit 1
    fi
    .venv/bin/python -m pip install --upgrade pip
fi

echo "Checking dependencies..."
.venv/bin/python -m pip install --quiet --disable-pip-version-check -e ".[dev,garmin,app]"

echo "Starting flexTri; it opens in your browser. Press Ctrl+C here or Quit in the app to stop it."
exec .venv/bin/python -m flextri.launcher
