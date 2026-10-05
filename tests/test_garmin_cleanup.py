from datetime import date

from flextri.garmin_cleanup import delete_old, scan


class FakeLibrary:
    def __init__(self, workouts, calendar):
        self.workouts, self.calendar, self.deleted = workouts, calendar, []

    def get_workouts(self, start=0, limit=100):
        return self.workouts[start:start + limit]

    def get_scheduled_workouts(self, year, month):
        prefix = f"{year}-{month:02d}-"
        return {"calendarItems": [c for c in self.calendar if c["date"].startswith(prefix)]}

    def delete_workout(self, workout_id):
        self.deleted.append(workout_id)


def test_only_workouts_scheduled_entirely_in_the_past_are_deleted():
    workouts = [{"workoutId": i, "workoutName": f"w{i}"} for i in range(1, 205)]
    calendar = [{"itemType": "workout", "workoutId": i, "date": "2026-08-15"} for i in range(1, 201)]
    calendar += [
        {"itemType": "workout", "workoutId": 201, "date": "2026-10-04"},  # today: keep
        {"itemType": "workout", "workoutId": 202, "date": "2026-09-01"},
        {"itemType": "workout", "workoutId": 202, "date": "2026-11-01"},  # also upcoming: keep
        {"itemType": "activity", "workoutId": 203, "date": "2026-09-01"},  # not a workout item
    ]
    lib = FakeLibrary(workouts, calendar)
    report = scan(lib, date(2026, 10, 4))
    assert (report.total, len(report.old), report.upcoming, report.unscheduled) == (204, 200, 2, 2)
    assert delete_old(lib, report) == 200
    assert lib.deleted == list(range(1, 201))
