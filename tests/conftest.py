import pytest

from flextri import token_vault
from flextri.paths import bundled
from flextri.storage import load_template

EXAMPLE = bundled("examples", "placeholder_plan.json")


@pytest.fixture
def template():
    return load_template(EXAMPLE)


@pytest.fixture
def example_path():
    return EXAMPLE


@pytest.fixture(autouse=True)
def _private_data_dir(tmp_path, monkeypatch):
    """Keep every test out of the real per-user data folder."""
    monkeypatch.setenv("FLEXTRI_HOME", str(tmp_path / "flextri-home"))


class MemoryKeyring:
    """A password store that lives only for one test."""

    def __init__(self):
        self.saved = {}

    def get_password(self, service, name):
        return self.saved.get((service, name))

    def set_password(self, service, name, value):
        self.saved[(service, name)] = value


@pytest.fixture(autouse=True)
def system_keyring(monkeypatch):
    """Keep every test out of the real password store (Credential Manager, Keychain, keyring)."""
    keyring = MemoryKeyring()
    monkeypatch.setattr(token_vault, "_system_keyring", lambda: keyring)
    return keyring
