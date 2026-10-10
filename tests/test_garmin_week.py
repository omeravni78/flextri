"""Sending a week to Garmin from the calendar and the three Today looks, answered in place."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from flextri.storage import SqliteStore
from flextri.web import api, garmin_ui
from flextri.web.garmin_week import window

TODAY = date(2026, 10, 7)  # a Wednesday
FORM = {
    "name": "omer", "experience": "some", "race_date": "2026-12-27", "start_date": "2026-10-04",
    "distance": "olympic", "goal": "finish", "week_start": "6", "plan": "olympic_8week_triathlete",
    "available_days": ["1", "2", "3", "5", "6"], "max_weekday_min": "", "max_weekend_min": "", "long_day": "",
}


class FakeGarmin:
    def __init__(self):
        self.uploaded, self.scheduled = [], []

    def get_scheduled_workouts(self, year, month):
        return {"calendarItems": []}

    def upload_workout(self, payload):
        self.uploaded.append(payload)
        return {"workoutId": len(self.uploaded)}

    def schedule_workout(self, workout_id, date_str):
        self.scheduled.append((workout_id, date_str))


class Account:
    waiting_for_code = False

    def __init__(self, connected=True):
        self.connected, self.fake = connected, FakeGarmin()

    def client(self):
        return self.fake


@pytest.fixture
def account():
    return Account()


@pytest.fixture
def client(tmp_path, account):
    store = SqliteStore(tmp_path / "ui.db")
    api.app.dependency_overrides[api.get_store] = lambda: store
    api.app.dependency_overrides[api.get_today] = lambda: TODAY
    api.app.dependency_overrides[garmin_ui.get_account] = lambda: account
    c = TestClient(api.app, follow_redirects=False)
    c.post("/setup", data=FORM)
    yield c
    api.app.dependency_overrides.clear()


def test_window_never_sends_the_past():
    assert window(TODAY, None, 7) == (TODAY, 7)
    assert window(TODAY, TODAY - timedelta(days=3), 7) == (TODAY, 4)
    assert window(TODAY, TODAY - timedelta(days=7), 7) is None
    assert window(TODAY, TODAY + timedelta(days=4), 99) == (TODAY + timedelta(days=4), 14)


def test_calendar_has_a_button_per_week_that_answers_in_place(client):
    cal = client.get("/calendar").text
    assert cal.count('hx-post="/ui/garmin/send"') == 4  # this week on top, then each later week
    assert 'id="garmin-out"' in cal and "Send this week to Garmin" in cal
    later = client.get("/ui/calendar?around=2026-10-25").text
    assert "Send week 4 to Garmin" in later and '"start": "2026-10-25"' in later


def test_past_weeks_have_no_send_button(client):
    assert 'hx-post="/ui/garmin/send"' not in client.get("/ui/calendar?around=2026-09-20").text.split('class="grid"')[0]


def test_sends_only_the_chosen_week(client, account):
    note = client.post("/ui/garmin/send", data={"start": "2026-10-25", "days": "7"}).text
    days = {d for _, d in account.fake.scheduled}
    assert days and min(days) >= "2026-10-25" and max(days) <= "2026-10-31"
    assert "Sync your watch" in note and "What went to Garmin" in note
    assert "<html" not in note  # a fragment for the screen, not the Garmin page


def test_not_connected_points_to_the_garmin_page(client, account):
    account.connected = False
    note = client.post("/ui/garmin/send", data={"days": "7"}).text
    assert 'href="/garmin"' in note and not account.fake.uploaded


@pytest.mark.parametrize("look", ["lanes", "chat", "bigday"])
def test_every_look_sends_in_place(client, look):
    client.post("/look", data={"look": look})
    home = client.get("/").text
    assert f"lk-{look}" in home
    assert 'hx-post="/ui/garmin/send"' in home and 'class="gsend-out"' in home
