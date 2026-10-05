from flextri import paths


def test_data_lives_in_the_app_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("FLEXTRI_DB", raising=False)
    monkeypatch.delenv("GARMINTOKENS", raising=False)
    home = tmp_path / "flextri-home"
    assert paths.db_path() == home / "flextri.db"
    assert paths.garmin_tokens() == home / "garmin"
    assert paths.log_dir() == home / "logs" and paths.log_dir().is_dir()


def test_env_overrides_win(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEXTRI_DB", str(tmp_path / "x.db"))
    monkeypatch.setenv("GARMINTOKENS", str(tmp_path / "tok"))
    assert paths.db_path() == tmp_path / "x.db"
    assert paths.garmin_tokens() == tmp_path / "tok"


def test_old_database_and_tokens_are_copied_once(tmp_path, monkeypatch):
    monkeypatch.delenv("FLEXTRI_DB", raising=False)
    monkeypatch.delenv("GARMINTOKENS", raising=False)
    old_db = tmp_path / "checkout" / "flextri.db"
    old_db.parent.mkdir()
    old_db.write_bytes(b"old")
    old_tokens = tmp_path / ".garminconnect"
    old_tokens.mkdir()
    (old_tokens / "garmin_tokens.json").write_text("{}")
    monkeypatch.setattr(paths, "LEGACY_DB", old_db)
    monkeypatch.setattr(paths, "LEGACY_TOKENS", old_tokens)

    assert paths.db_path().read_bytes() == b"old"
    assert (paths.garmin_tokens() / "garmin_tokens.json").read_text() == "{}"

    old_db.write_bytes(b"newer")  # only the first run copies; after that the app's own file wins
    assert paths.db_path().read_bytes() == b"old"


def test_plans_ship_inside_the_package():
    assert (paths.bundled("plans") / "olympic_8week_triathlete.json").is_file()
    assert (paths.bundled("examples") / "placeholder_plan.json").is_file()
