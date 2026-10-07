from datetime import date

import pytest
from fastapi.testclient import TestClient

from flextri.storage import SqliteStore
from flextri.web import api

TODAY = date(2026, 10, 7)  # a Wednesday

FORM = {
    "name": "omer", "experience": "some", "race_date": "2026-12-27", "start_date": "2026-10-04",
    "distance": "olympic", "goal": "finish", "week_start": "6",
    "available_days": ["1", "2", "3", "5", "6"], "max_weekday_min": "", "max_weekend_min": "", "long_day": "",
}


@pytest.fixture
def client(tmp_path):
    store = SqliteStore(tmp_path / "ui.db")
    api.app.dependency_overrides[api.get_store] = lambda: store
    api.app.dependency_overrides[api.get_today] = lambda: TODAY
    yield TestClient(api.app, follow_redirects=False)
    api.app.dependency_overrides.clear()


def _key_id(client, day):
    html = client.get(f"/ui/day/{day}").text
    return html.split('name="workout_id" value="')[1].split('"')[0]


def test_new_athlete_lands_on_wizard(client):
    r = client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    assert "build your plan" in client.get("/setup").text
    assert client.get("/static/htmx.min.js").status_code == 200


def test_preview_shows_fit_and_errors(client):
    html = client.post("/ui/preview", data=FORM).text
    assert "fitted to <strong>13 weeks</strong>" in html and "taper" in html and "Your first two weeks" in html
    bad = client.post("/ui/preview", data={**FORM, "available_days": ["1", "2"]}).text
    assert "Pick at least 3 training days" in bad


def test_wizard_to_calendar_and_day_actions(client):
    r = client.post("/setup", data=FORM)
    assert r.headers["HX-Redirect"] == "/?saved=1"
    home = client.get("/?saved=1").text
    assert "Week 1 of 13" in home and "Your setup is saved." in home
    cal = client.get("/calendar").text
    assert cal.index(">Sun<") < cal.index(">Mon<")  # week starts Sunday

    wid = _key_id(client, "2026-10-07")
    html = client.post("/ui/day/2026-10-07/action", data={"kind": "easier", "workout_id": wid}).text
    assert "Wed 7 Oct bike is now 42 min" in html and "Undo" in html
    html = client.post("/ui/day/2026-10-07/action", data={"kind": "swap", "workout_id": wid, "discipline": "run"}).text
    assert "banner error" in html and "Key sessions" in html
    assert "Undid easier" in client.post("/ui/undo").text

    html = client.post("/ui/day/2026-10-07/checkin", data={"workout_id": wid, "outcome": "done", "minutes": "60", "rpe": "9", "fatigue": "4"}).text
    assert "Checked in." in html and "Eased" in html
    html = client.post("/ui/day/2026-10-01/checkin", data={"outcome": "done"}).text
    assert "today or up to 2 days back" in html


def test_edit_setup_prefills_and_previews_changes(client):
    client.post("/setup", data=FORM)
    page = client.get("/setup").text
    assert "Edit my setup" in page and 'value="omer"' in page
    html = client.post("/ui/preview", data={**FORM, "race_date": "2027-01-10"}).text
    assert "2 weeks added" in html
    assert client.post("/setup", data={**FORM, "race_date": "2027-01-10"}).status_code == 200
    assert "Week 1 of 15" in client.get("/ui/calendar?around=2026-10-04").text


def test_wizard_offers_plans_and_builds_the_chosen_one(client):
    html = client.get("/setup").text
    assert 'name="plan" value="olympic_8week_triathlete"' in html
    assert 'name="plan" value="placeholder_plan"' in html
    form = {**FORM, "plan": "olympic_8week_triathlete"}
    assert "Triathlete.com 8-week Olympic plan" in client.post("/ui/preview", data=form).text
    assert client.post("/setup", data=form).headers["HX-Redirect"] == "/?saved=1"
    cal = client.get("/calendar").text
    assert "Triathlete.com 8-week Olympic plan" in cal and "Week 1 of" in cal


def test_unknown_plan_is_rejected(client):
    html = client.post("/ui/preview", data={**FORM, "plan": "nope"}).text
    assert "Unknown plan" in html


def test_wizard_day_choices_reach_the_plan(client):
    html = client.get("/setup").text
    assert 'name="long_ride_day"' in html and 'name="brick_day"' in html and "Swim days" in html
    form = {**FORM, "plan": "olympic_8week_triathlete", "long_ride_day": "6", "long_run_day": "5",
            "brick_day": "3", "pool_days": ["2", "5"]}
    assert "long ride Sun, long run Sat, brick Thu" in client.post("/ui/preview", data=form).text
    client.post("/setup", data=form)
    a = api.get_profile(store=api.app.dependency_overrides[api.get_store]())
    assert (a["long_ride_day"], a["long_run_day"], a["brick_day"], sorted(a["pool_days"])) == (6, 5, 3, [2, 5])


def test_preview_warns_when_too_few_days(client):
    form = {**FORM, "plan": "olympic_8week_triathlete", "available_days": ["0", "2", "5"]}
    assert "leaves out the easier ones" in client.post("/ui/preview", data=form).text


def test_calendar_sends_this_week_to_garmin(client):
    from flextri.web import garmin_ui

    class FakeGarmin:
        uploaded, scheduled = [], []

        def get_scheduled_workouts(self, year, month):
            return {"calendarItems": []}

        def upload_workout(self, payload):
            self.uploaded.append(payload)
            return {"workoutId": len(self.uploaded)}

        def schedule_workout(self, workout_id, date_str):
            self.scheduled.append((workout_id, date_str))

    fake = FakeGarmin()

    class Connected:
        connected, waiting_for_code = True, False

        def client(self):
            return fake

    client.post("/setup", data={**FORM, "plan": "olympic_8week_triathlete"})
    cal = client.get("/calendar").text
    assert 'href="/garmin"' in cal and 'action="/garmin/send"' in cal
    api.app.dependency_overrides[garmin_ui.get_account] = lambda: Connected()
    page = client.post("/garmin/send").text
    assert fake.uploaded and "Sync your watch" in page
    assert all(day >= TODAY.isoformat() for _, day in fake.scheduled)
