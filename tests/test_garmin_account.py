from datetime import date

import pytest
from fastapi.testclient import TestClient

from flextri.garmin_account import CODE_TIMEOUT_S, TOKEN_FILE, GarminAccount, GarminLoginError
from flextri.storage import SqliteStore
from flextri.web import api, garmin_ui

TODAY = date(2026, 10, 7)
PROFILE = {
    "name": "omer", "experience": "some", "weekly_hours": 6, "race_date": "2026-12-27",
    "distance": "olympic", "goal": "finish", "start_date": "2026-10-04", "week_start": 6,
    "available_days": [1, 2, 3, 5, 6], "max_weekday_min": 60, "max_weekend_min": 120,
}


class AuthError(Exception):
    pass


AuthError.__name__ = "GarminConnectAuthenticationError"


class FakeInner:
    def dumps(self):
        return '{"di_token": "t"}'


class FakeGarmin:
    """Stands in for garminconnect.Garmin, recording what flexTri asks of it."""

    mfa = False
    good_code = "123456"

    def __init__(self, email=None, password=None):
        self.email, self.password = email, password
        self.client = FakeInner()
        self.uploaded, self.scheduled, self.deleted = [], [], []
        self.library = [{"workoutId": 1, "workoutName": "old TP session"}, {"workoutId": 2, "workoutName": "mine"}]

    def login(self, tokenstore=None):
        if tokenstore is not None:
            return None, None
        if self.password != "right":
            raise AuthError("401")
        return ("needs_mfa", None) if self.mfa else (None, None)

    def resume_login(self, state, code):
        if code != self.good_code:
            raise AuthError("bad code")
        return None, None

    def get_scheduled_workouts(self, year, month):
        if (year, month) == (2026, 1):
            return {"calendarItems": [{"itemType": "workout", "workoutId": 1, "date": "2026-01-03"}]}
        return {"calendarItems": []}

    def upload_workout(self, payload):
        self.uploaded.append(payload)
        return {"workoutId": 100 + len(self.uploaded)}

    def schedule_workout(self, workout_id, date_str):
        self.scheduled.append((workout_id, date_str))

    def get_workouts(self, start=0, limit=100):
        return [w for w in self.library if w["workoutId"] not in self.deleted][start:start + limit]

    def delete_workout(self, workout_id):
        self.deleted.append(workout_id)


@pytest.fixture
def made():
    return []


@pytest.fixture
def account(tmp_path, made):
    def factory(email=None, password=None):
        made.append(FakeGarmin(email, password))
        return made[-1]
    return GarminAccount(tmp_path / "tokens", factory=factory)


def test_connect_saves_tokens_and_forgets_password(account, made):
    assert not account.connected
    assert account.connect(" me@x.com ", "right") is True
    assert account.connected
    assert made[0].email == "me@x.com" and made[0].password is None
    saved = (account.tokens / TOKEN_FILE).read_text()
    assert "right" not in saved and "di_token" in saved


def test_wrong_password_is_readable_and_saves_nothing(account):
    with pytest.raises(GarminLoginError, match="didn't accept"):
        account.connect("me@x.com", "wrong")
    assert not account.connected


def test_two_step_code_flow(account, made, monkeypatch):
    monkeypatch.setattr(FakeGarmin, "mfa", True)
    assert account.connect("me@x.com", "right") is False
    assert account.waiting_for_code and not account.connected
    assert made[0].password is None
    with pytest.raises(GarminLoginError):
        account.submit_code("000000")
    assert account.waiting_for_code  # a typo doesn't end the login
    account.submit_code(" 123 456 ")
    assert account.connected and not account.waiting_for_code


def test_code_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(FakeGarmin, "mfa", True)
    now = [0.0]
    account = GarminAccount(tmp_path, factory=FakeGarmin, clock=lambda: now[0])
    account.connect("me@x.com", "right")
    now[0] = CODE_TIMEOUT_S + 1
    assert not account.waiting_for_code
    with pytest.raises(GarminLoginError, match="timed out"):
        account.submit_code("123456")


def test_disconnect_deletes_tokens(account):
    account.connect("me@x.com", "right")
    (account.tokens / "oauth1_token.json").write_text("{}")
    account.disconnect()
    assert not account.connected
    assert not (account.tokens / "oauth1_token.json").exists()
    with pytest.raises(GarminLoginError, match="Connect Garmin first"):
        account.client()


@pytest.fixture
def web(tmp_path, account):
    store = SqliteStore(tmp_path / "t.db")
    api.app.dependency_overrides[api.get_store] = lambda: store
    api.app.dependency_overrides[api.get_today] = lambda: TODAY
    api.app.dependency_overrides[garmin_ui.get_account] = lambda: account
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_page_walks_from_login_to_send_cleanup_and_disconnect(web, account, made):
    page = web.get("/garmin").text
    assert "Not connected" in page and 'name="password"' in page

    page = web.post("/garmin/connect", data={"email": "me@x.com", "password": "wrong"}).text
    assert "accept that" in page and 'value="me@x.com"' in page

    page = web.post("/garmin/connect", data={"email": "me@x.com", "password": "right"}).text
    assert "Garmin connected" in page and "Send this week to watch" in page

    assert "Finish the setup first" in web.post("/garmin/send").text
    assert web.put("/api/profile", json=PROFILE).status_code == 200
    page = web.post("/garmin/send").text
    sender = made[-1]
    assert sender.uploaded and "Sync your watch" in page
    assert all(d >= TODAY.isoformat() for _, d in sender.scheduled)

    page = web.post("/garmin/cleanup").text
    assert "Delete 1 old workout" in page and "old TP session" in page
    assert made[-1].deleted == []  # checking deletes nothing
    page = web.post("/garmin/cleanup/confirm").text
    assert made[-1].deleted == [1] and "Deleted 1 old workout" in page

    page = web.post("/garmin/disconnect").text
    assert "Garmin disconnected" in page and not account.connected


def test_page_asks_for_code(web, monkeypatch):
    monkeypatch.setattr(FakeGarmin, "mfa", True)
    page = web.post("/garmin/connect", data={"email": "me@x.com", "password": "right"}).text
    assert 'name="code"' in page
    assert "Garmin connected" in web.post("/garmin/code", data={"code": "123456"}).text


def test_library_problem_explains_old_python(monkeypatch):
    import sys
    from importlib import metadata

    from flextri import garmin_account

    monkeypatch.setattr(metadata, "version", lambda name: "0.3.2")
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    assert "Python 3.11" in garmin_account.library_problem()
    monkeypatch.setattr(sys, "version_info", (3, 12, 4))
    assert "out of date (0.3.2)" in garmin_account.library_problem()
    monkeypatch.setattr(metadata, "version", lambda name: "0.3.17")
    assert garmin_account.library_problem() is None


def test_login_errors_say_what_garmin_said(account):
    with pytest.raises(GarminLoginError, match="Garmin said: 401"):
        account.connect("me@x.com", "wrong")


def test_page_warns_about_old_library(web, monkeypatch):
    monkeypatch.setattr(garmin_ui, "library_problem", lambda: "The Garmin library is out of date (0.3.2).")
    assert "out of date (0.3.2)" in web.get("/garmin").text


def test_library_problem_names_the_start_script_for_this_system(monkeypatch):
    import sys
    from importlib import metadata

    from flextri import garmin_account

    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    monkeypatch.setattr(sys, "platform", "linux")
    assert "./run-linux.sh" in garmin_account.library_problem()
    monkeypatch.setattr(sys, "platform", "win32")
    assert "run-windows.bat" in garmin_account.library_problem()
