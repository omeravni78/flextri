from datetime import date

import pytest
from fastapi.testclient import TestClient

from flextri.garmin_account import GarminAccount
from flextri.garmin_calendar import by_day, read_week, remove
from flextri.storage import SqliteStore
from flextri.web import api, garmin_ui

TODAY = date(2026, 10, 29)  # the week runs into November, so two calendar months are read
PROFILE = {
    "name": "omer", "experience": "some", "weekly_hours": 6, "race_date": "2026-12-27",
    "distance": "olympic", "goal": "finish", "start_date": "2026-10-04", "week_start": 6,
    "available_days": [1, 2, 3, 5, 6], "max_weekday_min": 60, "max_weekend_min": 120,
}


def item(sid, wid, day, title, sport="running", secs=None, kind="workout"):
    return {"id": sid, "itemType": kind, "workoutId": wid, "date": day, "title": title,
            "sportTypeKey": sport, "estimatedDurationInSecs": secs}


class FakeCalendar:
    """The Garmin calendar as garminconnect returns it, month by month."""

    def __init__(self, items):
        self.items = list(items)
        self.unscheduled, self.deleted, self.months = [], [], []

    def get_scheduled_workouts(self, year, month):
        self.months.append((year, month))
        return {"calendarItems": [i for i in self.items if i["date"].startswith(f"{year}-{month:02d}")]}

    def unschedule_workout(self, sid):
        self.unscheduled.append(sid)
        self.items = [i for i in self.items if i["id"] != sid]

    def delete_workout(self, wid):
        self.deleted.append(wid)
        self.items = [i for i in self.items if i["workoutId"] != wid]


def week_items():
    return [
        item(1, 11, "2026-10-28", "flexTri: yesterday's run"),  # before the window
        item(2, 12, "2026-10-29", "flexTri: easy run", secs=2400),
        item(3, 13, "2026-10-31", "flexTri: Long ride", "cycling", 5400),
        item(4, 14, "2026-11-02", "Track Tuesday", "running"),  # the athlete's own workout
        item(5, 15, "2026-11-02", "flexTri: swim", "swimming", 1800),
        item(6, None, "2026-11-01", "Parkrun", kind="activity"),  # recorded activity, not a plan
        item(7, 16, "2026-11-05", "flexTri: after the window"),
    ]


def test_read_week_spans_months_and_keeps_only_workouts_in_the_window():
    cal = FakeCalendar(week_items())
    week = read_week(cal, TODAY, 7)
    assert [s.schedule_id for s in week] == [2, 3, 4, 5]
    assert set(cal.months) == {(2026, 10), (2026, 11)}
    run, ride, track, swim = week
    assert (run.title, run.sport, run.minutes, run.from_flextri) == ("easy run", "run", 40, True)
    assert (ride.sport, ride.minutes) == ("bike", 90)
    assert (track.from_flextri, track.minutes) == (False, None)
    assert swim.sport == "swim"


def test_by_day_lists_every_day_including_empty_ones():
    days = by_day(read_week(FakeCalendar(week_items()), TODAY, 7), TODAY, 7)
    assert len(days) == 7 and days[0][0] == TODAY
    assert [len(items) for _, items in days] == [1, 0, 1, 0, 2, 0, 0]


def test_remove_deletes_flextri_workouts_and_only_unschedules_the_athletes_own():
    cal = FakeCalendar(week_items())
    removed = remove(cal, TODAY, 7, [2, 4, 7, 1])  # 7 and 1 are outside the window: left alone
    assert {s.schedule_id for s in removed} == {2, 4}
    assert cal.deleted == [12]
    assert cal.unscheduled == [4]
    assert [s.schedule_id for s in read_week(cal, TODAY, 7)] == [3, 5]


def test_remove_keeps_a_flextri_workout_that_is_also_on_another_day():
    items = [item(2, 12, "2026-10-29", "flexTri: easy run"), item(9, 12, "2026-11-10", "flexTri: easy run")]
    cal = FakeCalendar(items)
    remove(cal, TODAY, 7, [2])
    assert cal.deleted == [] and cal.unscheduled == [2]


def test_remove_deletes_a_shared_flextri_workout_once_when_all_its_days_go():
    items = [item(2, 12, "2026-10-29", "flexTri: easy run"), item(9, 12, "2026-10-30", "flexTri: easy run")]
    cal = FakeCalendar(items)
    assert len(remove(cal, TODAY, 7, [2, 9])) == 2
    assert cal.deleted == [12] and cal.unscheduled == []


# ---------- the page ----------

class Connected(GarminAccount):
    def __init__(self, cal):
        super().__init__()
        self.cal = cal

    @property
    def connected(self):
        return True

    def client(self):
        return self.cal


@pytest.fixture
def cal():
    return FakeCalendar(week_items())


@pytest.fixture
def web(tmp_path, cal):
    store = SqliteStore(tmp_path / "t.db")
    api.app.dependency_overrides[api.get_store] = lambda: store
    api.app.dependency_overrides[api.get_today] = lambda: TODAY
    api.app.dependency_overrides[garmin_ui.get_account] = lambda: Connected(cal)
    client = TestClient(api.app)
    assert client.put("/api/profile", json=PROFILE).status_code == 200
    yield client
    api.app.dependency_overrides.clear()


@pytest.mark.parametrize("look", ["bigday", "lanes", "chat"])
def test_week_and_delete_in_every_look(web, cal, look):
    web.post("/look", data={"look": look})
    page = web.get("/garmin").text
    assert f'class="g g-{look}"' in page and 'hx-get="/garmin/week"' in page

    week = web.get("/garmin/week").text
    assert "what Garmin thinks your week will look like" in week
    assert "easy run" in week and "Long ride" in week and "Track Tuesday" in week
    assert "Parkrun" not in week and "after the window" not in week
    assert "Not flexTri" in week or "not from flexTri" in week
    assert 'name="all" value="1"' in week and "Delete all 4" in week

    ask = web.post("/garmin/week/delete", data={"ids": ["2", "4"]}).text
    assert cal.deleted == [] and cal.unscheduled == []  # asking deletes nothing
    assert "can’t be undone" in ask and ask.count('type="hidden" name="ids"') == 2

    done = web.post("/garmin/week/delete/confirm", data={"ids": ["2", "4"]}).text
    assert cal.deleted == [12] and cal.unscheduled == [4]
    assert "Deleted 2 sessions from Garmin" in done and "easy run" not in done


def test_delete_all_and_nothing_ticked(web, cal):
    assert "Tick the sessions" in web.post("/garmin/week/delete", data={}).text
    ask = web.post("/garmin/week/delete", data={"all": "1"}).text
    assert ask.count('type="hidden" name="ids"') == 4
    web.post("/garmin/week/delete/confirm", data={"ids": ["2", "3", "4", "5"]})
    assert sorted(cal.deleted) == [12, 13, 15] and cal.unscheduled == [4]
    assert "nothing scheduled" in web.get("/garmin/week").text


def test_week_shows_garmin_errors(web, cal, monkeypatch):
    def broken(year, month):
        raise RuntimeError("Garmin is down")
    monkeypatch.setattr(cal, "get_scheduled_workouts", broken)
    week = web.get("/garmin/week").text
    assert "read your Garmin calendar: Garmin is down" in week
    assert "Try again" in week
