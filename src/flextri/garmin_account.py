"""Connect flexTri to Garmin Connect from the web app.

The athlete types their Garmin email and password once (plus the two-step code if
Garmin asks for one). flexTri never writes the password anywhere: it logs in,
keeps only Garmin's login tokens in the same folder the command line uses
(``GARMINTOKENS``, default ``~/.garminconnect``), and forgets the password. After
that, ``python -m flextri.garmin`` and the web page share the same connection.
Disconnecting deletes the tokens.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

TOKEN_FILE = "garmin_tokens.json"
# Files older garminconnect releases (built on garth) wrote; removed on disconnect too.
LEGACY_TOKEN_FILES = ("oauth1_token.json", "oauth2_token.json")
CODE_TIMEOUT_S = 10 * 60


class GarminLoginError(Exception):
    """A login problem worth showing to the athlete as is."""


def token_dir() -> Path:
    return Path(os.environ.get("GARMINTOKENS", "~/.garminconnect")).expanduser()


def _garmin_factory(email: str | None = None, password: str | None = None) -> Any:
    try:
        from garminconnect import Garmin
    except ImportError:
        raise GarminLoginError("Install the Garmin client first: pip install garminconnect") from None
    return Garmin(email, password, return_on_mfa=True)


def _readable(e: Exception) -> str:
    kind = type(e).__name__
    if "TooManyRequests" in kind:
        return "Garmin is limiting login attempts. Wait a few minutes and try again."
    if "Authentication" in kind:
        return "Garmin didn't accept that. Check your email, password or code and try again."
    first_line = str(e).strip().splitlines()[0] if str(e).strip() else kind
    return f"Couldn't reach Garmin Connect: {first_line}"


class GarminAccount:
    """The one Garmin connection of this install (one athlete per install)."""

    def __init__(self, tokens: Path | None = None, factory: Callable[..., Any] = _garmin_factory,
                 clock: Callable[[], float] = time.monotonic):
        self._tokens = tokens
        self._factory = factory
        self._clock = clock
        self._pending: tuple[Any, float] | None = None  # login waiting for the two-step code

    @property
    def tokens(self) -> Path:
        return self._tokens if self._tokens is not None else token_dir()

    @property
    def connected(self) -> bool:
        return (self.tokens / TOKEN_FILE).exists()

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
        garmin = self._factory()
        try:
            garmin.login(str(self.tokens))
        except GarminLoginError:
            raise
        except Exception:
            raise GarminLoginError("Garmin signed flexTri out. Disconnect and connect again.") from None
        return garmin

    def disconnect(self) -> None:
        self._pending = None
        for name in (TOKEN_FILE, *LEGACY_TOKEN_FILES):
            (self.tokens / name).unlink(missing_ok=True)

    def _save(self, garmin: Any) -> None:
        self.tokens.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.tokens / TOKEN_FILE
        path.write_text(garmin.client.dumps())
        path.chmod(0o600)
