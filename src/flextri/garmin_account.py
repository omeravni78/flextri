"""Connect flexTri to Garmin Connect from the web app.

The athlete types their Garmin email and password once (plus the two-step code if
Garmin asks for one). flexTri never writes the password anywhere: it logs in,
keeps only Garmin's login tokens, encrypted (see ``token_vault.py``), in the same
folder the command line uses (``GARMINTOKENS``, default ``garmin`` in flexTri's data
folder, see ``paths.py``), and forgets the password. After that, ``python -m flextri.garmin`` and the web
page share the same connection.
Disconnecting deletes the tokens.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import paths
from .token_vault import PLAIN_FILE, TokenVault, TokenVaultError

log = logging.getLogger(__name__)

TOKEN_FILE = PLAIN_FILE  # what flexTri 0.2 and older saved unencrypted; encrypted on first read
# Files older garminconnect releases (built on garth) wrote; removed on disconnect too.
LEGACY_TOKEN_FILES = ("oauth1_token.json", "oauth2_token.json")
CODE_TIMEOUT_S = 10 * 60
# garminconnect keeps up with changes to Garmin's login. Releases after 0.3.2 need Python 3.12, so on
# Python 3.11 pip silently stays on 0.3.2 (April 2026) and misses months of login fixes.
MIN_LIBRARY = (0, 3, 17)


class GarminLoginError(Exception):
    """A login problem worth showing to the athlete as is."""


def token_dir() -> Path:
    return paths.garmin_tokens()


def _garmin_factory(email: str | None = None, password: str | None = None) -> Any:
    try:
        from garminconnect import Garmin
    except ImportError:
        raise GarminLoginError("Install the Garmin client first: pip install garminconnect") from None
    return Garmin(email, password, return_on_mfa=True)


def _run_script() -> str:
    """The start script for this system; it builds .venv with the Garmin library."""
    return "run-windows.bat" if sys.platform == "win32" else "./run-linux.sh"


def library_problem() -> str | None:
    """Why Garmin login can't work in this install, or None. Shown on the Garmin page."""
    try:
        from importlib.metadata import PackageNotFoundError, version
        installed = version("garminconnect")
    except PackageNotFoundError:
        return (f"The Garmin library isn't installed. Start flexTri with {_run_script()}, "
                "or run: pip install -e \".[garmin]\"")
    numbers = tuple(int(n) for n in installed.split(".")[:3] if n.isdigit())
    if numbers >= MIN_LIBRARY:
        return None
    if sys.version_info < (3, 12):
        return (f"This flexTri runs on Python {sys.version_info[0]}.{sys.version_info[1]}, which only gets an old "
                f"Garmin library ({installed}), missing months of fixes for Garmin's login. Install Python 3.12 or newer "
                f"from python.org, then start {_run_script()} again: it rebuilds flexTri on the new Python.")
    return (f"The Garmin library is out of date ({installed}). Start {_run_script()} again to update it, "
            "or run: pip install -U garminconnect")


def _detail(e: Exception) -> str:
    text = str(e).strip()
    return text.splitlines()[0][:300] if text else type(e).__name__


def _readable(e: Exception) -> str:
    log.warning("Garmin login failed", exc_info=e)
    kind = type(e).__name__
    if "TooManyRequests" in kind:
        return "Garmin is limiting login attempts. Wait a few minutes and try again."
    if "Authentication" in kind:
        return f"Garmin didn't accept that. Check your email, password or code and try again. (Garmin said: {_detail(e)})"
    return f"Couldn't log in to Garmin Connect: {_detail(e)}"


class GarminAccount:
    """The one Garmin connection of this install (one athlete per install)."""

    def __init__(self, tokens: Path | None = None, factory: Callable[..., Any] = _garmin_factory,
                 clock: Callable[[], float] = time.monotonic, keyring: Any | None = None):
        self._tokens = tokens
        self._factory = factory
        self._clock = clock
        self._keyring = keyring
        self._pending: tuple[Any, float] | None = None  # login waiting for the two-step code

    @property
    def tokens(self) -> Path:
        return self._tokens if self._tokens is not None else token_dir()

    @property
    def vault(self) -> TokenVault:
        return TokenVault(self.tokens, keyring=self._keyring)

    @property
    def connected(self) -> bool:
        return self.vault.exists()

    def protection(self) -> str:
        return self.vault.protection()

    @property
    def waiting_for_code(self) -> bool:
        return self._pending is not None and self._clock() - self._pending[1] < CODE_TIMEOUT_S

    def connect(self, email: str, password: str) -> bool:
        """Log in. True when connected, False when Garmin wants a two-step code first."""
        email = email.strip()
        if not email or not password:
            raise GarminLoginError("Enter your Garmin email and password.")
        self._pending = None
        garmin = self._factory(email, password)
        try:
            status, _ = garmin.login()
        except GarminLoginError:
            raise
        except Exception as e:
            raise GarminLoginError(_readable(e)) from None
        finally:
            garmin.password = None  # never kept past the login call
        if status == "needs_mfa":
            self._pending = (garmin, self._clock())
            return False
        self._save(garmin)
        return True

    def submit_code(self, code: str) -> None:
        if not self.waiting_for_code:
            self._pending = None
            raise GarminLoginError("That login timed out. Enter your email and password again.")
        code = code.strip().replace(" ", "")
        if not code:
            raise GarminLoginError("Enter the code Garmin sent you.")
        garmin = self._pending[0]
        try:
            garmin.resume_login(None, code)
        except Exception as e:
            raise GarminLoginError(_readable(e)) from None  # keep the login open so they can retry
        self._pending = None
        self._save(garmin)

    def cancel(self) -> None:
        self._pending = None

    def client(self) -> Any:
        """A logged-in Garmin client from the saved tokens."""
        if not self.connected:
            raise GarminLoginError("Connect Garmin first.")
        vault = self.vault
        try:
            saved = vault.read()
        except TokenVaultError as e:
            log.warning("Saved Garmin login unreadable: %s", e)
            raise GarminLoginError(f"{str(e).capitalize()}. Disconnect and connect again.") from None
        garmin = self._factory()
        try:
            garmin.login(saved)  # the decrypted tokens go in as text, so the library never writes them to disk
        except GarminLoginError:
            raise
        except Exception as e:
            log.warning("Garmin rejected the saved login", exc_info=e)
            raise GarminLoginError(
                f"Garmin didn't accept flexTri's saved login. Disconnect and connect again. (Garmin said: {_detail(e)})"
            ) from None
        refreshed = garmin.client.dumps()
        if refreshed != saved:  # Garmin renewed the tokens while logging in
            vault.write(refreshed)
        return garmin

    def disconnect(self) -> None:
        self._pending = None
        self.vault.delete()
        for name in LEGACY_TOKEN_FILES:
            (self.tokens / name).unlink(missing_ok=True)

    def _save(self, garmin: Any) -> None:
        self.vault.write(garmin.client.dumps())
