"""Keep Garmin's login tokens encrypted on disk.

The tokens are encrypted with Fernet (AES, from ``cryptography``) into ``garmin_tokens.enc``. Only the
small key goes into the system's password store through ``keyring``: Windows Credential Manager, the
macOS Keychain, or the Secret Service keyring on Linux. A copied token file is useless without that key,
which the system only hands to the same user on the same computer.

Where no password store is available (a Linux box with no desktop keyring, say), the key goes into a
``token.key`` file only this user can read, next to the tokens. That still keeps the tokens from being
read as plain text, but someone who copies the whole folder can use them; ``protection()`` says which
case applies so the Garmin page can tell the athlete.

A plain ``garmin_tokens.json`` from an older flexTri is encrypted and deleted the first time it is read.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PLAIN_FILE = "garmin_tokens.json"
SECRET_FILE = "garmin_tokens.enc"
KEY_FILE = "token.key"
KEYRING_SERVICE = "flexTri"
KEYRING_NAME = "garmin-token-key"


class TokenVaultError(Exception):
    """The saved tokens can't be decrypted (the key is gone or the file was changed)."""


def _system_keyring() -> Any | None:
    """The keyring module when this system has a usable password store, else None."""
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:
        return None
    if isinstance(backend, fail.Keyring) or type(backend).__module__.startswith("keyring.backends.null"):
        return None
    return keyring


def _fernet(key: bytes) -> Any:
    from cryptography.fernet import Fernet
    return Fernet(key)


def _store_name(backend: Any) -> str:
    name = type(backend.get_keyring()).__module__ if hasattr(backend, "get_keyring") else ""
    if "Windows" in name:
        return "Windows Credential Manager"
    if "macOS" in name:
        return "the macOS Keychain"
    return "the system keyring"


class TokenVault:
    """Encrypted token storage in one folder (``paths.garmin_tokens()``)."""

    def __init__(self, folder: Path, keyring: Any | None = None, use_system_keyring: bool = True):
        self.folder = folder
        self._keyring = keyring
        self._use_system = use_system_keyring and keyring is None

    @property
    def path(self) -> Path:
        return self.folder / SECRET_FILE

    def exists(self) -> bool:
        return self.path.exists() or (self.folder / PLAIN_FILE).exists()

    def read(self) -> str | None:
        """The saved tokens as text, or None when there are none."""
        plain = self.folder / PLAIN_FILE
        if not self.path.exists():
            if not plain.exists():
                return None
            text = plain.read_text()
            self.write(text)  # encrypts, then removes the plain file
            log.info("Encrypted Garmin tokens saved by an older flexTri")
            return text
        from cryptography.fernet import InvalidToken
        key = self._key(create=False)
        if key is None:
            raise TokenVaultError("the key to flexTri's saved Garmin login is missing")
        try:
            return _fernet(key).decrypt(self.path.read_bytes()).decode("utf-8")
        except InvalidToken:
            raise TokenVaultError("flexTri's saved Garmin login can't be decrypted") from None

    def write(self, text: str) -> None:
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = _fernet(self._key(create=True)).encrypt(text.encode("utf-8"))
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, self.path)
        (self.folder / PLAIN_FILE).unlink(missing_ok=True)

    def delete(self) -> None:
        """Forget the tokens. The key stays, so a later connect reuses it."""
        self.path.unlink(missing_ok=True)
        (self.folder / PLAIN_FILE).unlink(missing_ok=True)

    def protection(self) -> str:
        """One line for the Garmin page on how the saved login is protected."""
        backend = self._backend()
        if backend is not None and not (self.folder / KEY_FILE).exists():
            return f"Saved encrypted. The key is kept in {_store_name(backend)}."
        return ("Saved encrypted, but this computer has no password store, so the key sits in a file "
                "only you can read next to it.")

    def _backend(self) -> Any | None:
        if self._keyring is not None:
            return self._keyring
        return _system_keyring() if self._use_system else None

    def _key(self, create: bool) -> bytes | None:
        key_file = self.folder / KEY_FILE
        if key_file.exists():
            return key_file.read_bytes().strip()
        backend = self._backend()
        if backend is not None:
            try:
                key = backend.get_password(KEYRING_SERVICE, KEYRING_NAME)
                if key:
                    return key.encode("ascii")
                if create:
                    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
                    backend.set_password(KEYRING_SERVICE, KEYRING_NAME, key)
                    return key.encode("ascii")
                return None
            except Exception as e:
                log.warning("Couldn't use the system password store, keeping the key in a file", exc_info=e)
        if not create:
            return None
        key = base64.urlsafe_b64encode(os.urandom(32))
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key
