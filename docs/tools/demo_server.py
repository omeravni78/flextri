"""Run flexTri with a fixed date and a pretend Garmin account, for the help-site screenshots.

    python docs/tools/demo_server.py           # http://127.0.0.1:8765, data in a temp folder
    python docs/tools/screenshots.py           # then, in a second terminal

Nothing here talks to Garmin: the fake account keeps sent workouts in memory.
"""

from __future__ import annotations

import itertools
import tempfile
from datetime import date
from pathlib import Path

import uvicorn

from flextri.storage import SqliteStore
from flextri.web import api, garmin_ui

TODAY = date(2026, 10, 14)  # a Wednesday in week 2 of the demo plan


class FakeGarmin:
    def __init__(self):
        self.ids = itertools.count(100)
        self.workouts: dict[int, dict] = {}
        # One workout the athlete made in Garmin Connect themselves.
        self.items = [{"itemType": "workout", "id": 99, "workoutId": 98, "date": "2026-10-17",
                       "title": "Easy spin with friends", "sportTypeKey": "cycling", "duration": 3600}]

    def get_scheduled_workouts(self, year, month):
        return {"calendarItems": [i for i in self.items if i["date"].startswith(f"{year}-{month:02d}")]}

    def upload_workout(self, payload):
        wid = next(self.ids)
        self.workouts[wid] = payload
        return {"workoutId": wid}

    def schedule_workout(self, workout_id, date_str):
        p = self.workouts[workout_id]
        self.items.append({"itemType": "workout", "id": next(self.ids), "workoutId": workout_id, "date": date_str,
                           "title": p["workoutName"], "sportTypeKey": p["sportType"]["sportTypeKey"],
                           "estimatedDurationInSecs": p.get("estimatedDurationInSecs")})

    def unschedule_workout(self, schedule_id):
        self.items = [i for i in self.items if i["id"] != int(schedule_id)]

    def delete_workout(self, workout_id):
        self.workouts.pop(int(workout_id), None)

    def get_workouts(self, start=0, limit=100):
        return []


class Account:
    waiting_for_code = False
    connected = False  # until the screenshots "log in" with any email and password

    def __init__(self):
        self.fake = FakeGarmin()

    def connect(self, email, password):
        self.connected = True
        return True

    def client(self):
        return self.fake

    def disconnect(self):
        self.connected = False


def main() -> None:
    store = SqliteStore(Path(tempfile.mkdtemp(prefix="flextri-demo-")) / "demo.db")
    account = Account()
    api.app.dependency_overrides[api.get_store] = lambda: store
    api.app.dependency_overrides[api.get_today] = lambda: TODAY
    api.app.dependency_overrides[garmin_ui.get_account] = lambda: account
    uvicorn.run(api.app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
