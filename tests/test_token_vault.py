import pytest

from flextri import token_vault
from flextri.garmin_account import GarminAccount, GarminLoginError
from flextri.token_vault import KEY_FILE, PLAIN_FILE, SECRET_FILE, TokenVault, TokenVaultError

TOKENS = '{"di_token": "secret-access", "di_refresh_token": "secret-refresh"}'


def test_tokens_are_encrypted_and_the_key_goes_to_the_password_store(tmp_path, system_keyring):
    vault = TokenVault(tmp_path / "garmin")
    vault.write(TOKENS)
    on_disk = (tmp_path / "garmin" / SECRET_FILE).read_bytes()
    assert b"secret" not in on_disk
    assert vault.read() == TOKENS
    assert list(system_keyring.saved) == [("flexTri", "garmin-token-key")]
    assert not (tmp_path / "garmin" / KEY_FILE).exists()
    assert "system keyring" in vault.protection()


def test_a_copied_file_is_useless_without_the_key(tmp_path, system_keyring):
    TokenVault(tmp_path / "garmin").write(TOKENS)
    other_computer = token_vault.TokenVault(tmp_path / "garmin", keyring=type(system_keyring)())
    with pytest.raises(TokenVaultError, match="missing"):
        other_computer.read()


def test_changed_file_is_refused(tmp_path):
    vault = TokenVault(tmp_path / "garmin")
    vault.write(TOKENS)
    vault.path.write_bytes(vault.path.read_bytes()[:-4] + b"AAAA")
    with pytest.raises(TokenVaultError, match="decrypted"):
        vault.read()


def test_plain_tokens_from_older_flextri_are_encrypted_on_first_read(tmp_path):
    folder = tmp_path / "garmin"
    folder.mkdir()
    (folder / PLAIN_FILE).write_text(TOKENS)
    vault = TokenVault(folder)
    assert vault.exists()
    assert vault.read() == TOKENS
    assert not (folder / PLAIN_FILE).exists()
    assert b"secret" not in (folder / SECRET_FILE).read_bytes()
    assert vault.read() == TOKENS


def test_without_a_password_store_the_key_goes_to_a_private_file(tmp_path, monkeypatch):
    monkeypatch.setattr(token_vault, "_system_keyring", lambda: None)
    vault = TokenVault(tmp_path / "garmin")
    vault.write(TOKENS)
    assert (tmp_path / "garmin" / KEY_FILE).exists()
    assert vault.read() == TOKENS
    assert "no password store" in vault.protection()


def test_broken_password_store_falls_back_to_the_key_file(tmp_path, monkeypatch):
    class Locked:
        def get_password(self, service, name):
            raise RuntimeError("locked")

    monkeypatch.setattr(token_vault, "_system_keyring", lambda: Locked())
    vault = TokenVault(tmp_path / "garmin")
    vault.write(TOKENS)
    assert vault.read() == TOKENS
    assert (tmp_path / "garmin" / KEY_FILE).exists()


def test_delete_removes_tokens_but_keeps_the_key(tmp_path, system_keyring):
    vault = TokenVault(tmp_path / "garmin")
    vault.write(TOKENS)
    vault.delete()
    assert not vault.exists() and vault.read() is None
    assert system_keyring.saved


class Garmin:
    def __init__(self, renewed=None):
        self.loaded = None
        self.renewed = renewed
        self.client = self

    def login(self, tokenstore=None):
        self.loaded = tokenstore

    def dumps(self):
        return self.renewed or self.loaded


def test_client_logs_in_from_decrypted_text_and_saves_renewed_tokens(tmp_path):
    made = []
    account = GarminAccount(tmp_path / "garmin", factory=lambda *a: made.append(Garmin('{"di_token": "new"}')) or made[-1])
    account.vault.write(TOKENS)
    account.client()
    assert made[0].loaded == TOKENS  # text, not a folder path the library would write plain tokens into
    assert account.vault.read() == '{"di_token": "new"}'


def test_unreadable_saved_login_asks_to_reconnect(tmp_path):
    account = GarminAccount(tmp_path / "garmin", factory=lambda *a: Garmin())
    account.vault.write(TOKENS)
    account.vault.path.write_bytes(b"junk")
    with pytest.raises(GarminLoginError, match="Disconnect and connect again"):
        account.client()
