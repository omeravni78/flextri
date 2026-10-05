"""Where flexTri keeps its files, so it runs the same from a checkout or as an installed app.

The athlete's data (database, Garmin login tokens, logs) lives in a per-user folder that survives
app updates: ``%LOCALAPPDATA%\\flexTri`` on Windows, ``~/Library/Application Support/flexTri`` on
macOS and ``~/.local/share/flextri`` on Linux. ``FLEXTRI_HOME`` moves the whole folder;
``FLEXTRI_DB`` and ``GARMINTOKENS`` still point at a single file or folder, as before.

Plans ship inside the package (``flextri/data``), so nothing is looked up next to the code.
"""

from __future__ import annotations

import os
import shutil
from importlib.resources import files
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "flexTri"
LEGACY_DB = Path("flextri.db")  # where run-windows.bat kept it: the folder the app started in
LEGACY_TOKENS = Path("~/.garminconnect").expanduser()


def data_dir() -> Path:
    home = os.environ.get("FLEXTRI_HOME")
    d = Path(home).expanduser() if home else Path(user_data_dir(APP_NAME, appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    """The SQLite file. The first time, an older ``flextri.db`` in the current folder is copied over."""
    if os.environ.get("FLEXTRI_DB"):
        return Path(os.environ["FLEXTRI_DB"])
    path = data_dir() / "flextri.db"
    if not path.exists() and LEGACY_DB.is_file():
        shutil.copy2(LEGACY_DB, path)
    return path


def garmin_tokens() -> Path:
    """Garmin login tokens. The first time, tokens from ``~/.garminconnect`` are copied over."""
    if os.environ.get("GARMINTOKENS"):
        return Path(os.environ["GARMINTOKENS"]).expanduser()
    path = data_dir() / "garmin"
    if not path.exists() and LEGACY_TOKENS.is_dir() and any(LEGACY_TOKENS.iterdir()):
        shutil.copytree(LEGACY_TOKENS, path)
    return path


def log_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(exist_ok=True)
    return d


def bundled(*parts: str) -> Path:
    """A file shipped inside the package, e.g. ``bundled("plans")``."""
    return Path(str(files("flextri").joinpath("data", *parts)))
