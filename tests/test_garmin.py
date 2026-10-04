from datetime import date

from flextri.garmin import push_schedule, to_garmin_workouts
from flextri.models import Athlete, Discipline, Phase, Schedule, ScheduledWorkout, Workout, WorkoutStatus


def _sw(id, day, discipline, minutes, intensity=2, desc="", status=WorkoutStatus.PLANNED):
    return ScheduledWorkout(id=id, date=day, workout=Workout(discipline, minutes, intensity, desc),
                            phase=Phase.BASE, status=status)


class FakeGarmin:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.uploaded, self.scheduled = [], []

    def get_scheduled_workouts(self, year, month):
        return {"calendarItems": self.existing}

    def upload_workout(self, payload):
        self.uploaded.append(payload)
        return {"workoutId": len(self.uploaded)}

    def schedule_workout(self, workout_id, date_str):
        self.scheduled.append((workout_id, date_str))
        return {}


def test_run_gets_warmup_main_cooldown_in_hr_zone():
    [p] = to_garmin_workouts(_sw(1, date(2026, 10, 6), Discipline.RUN, 40, 3, "tempo run"))
    assert p["workoutName"] == "flexTri: tempo run"
    assert p["sportType"]["sportTypeKey"] == "running"
    steps = p["workoutSegments"][0]["workoutSteps"]
    assert [s["stepType"]["stepTypeKey"] for s in steps] == ["warmup", "interval", "cooldown"]
    assert sum(s["endConditionValue"] for s in steps) == 40 * 60
    assert steps[1]["zoneNumber"] == 3


def test_swim_has_no_hr_target_and_short_session_is_one_step():
    [p] = to_garmin_workouts(_sw(1, date(2026, 10, 6), Discipline.SWIM, 15))
    [step] = p["workoutSegments"][0]["workoutSteps"]
    assert step["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert "zoneNumber" not in step


def test_brick_splits_into_ride_and_run_rest_is_skipped():
    bike, run = to_garmin_workouts(_sw(1, date(2026, 10, 6), Discipline.BRICK, 90, desc="brick"))
    assert (bike["estimatedDurationInSecs"], run["estimatedDurationInSecs"]) == (60 * 60, 30 * 60)
    assert to_garmin_workouts(_sw(2, date(2026, 10, 6), Discipline.REST, 0)) == []


def test_push_window_skips_done_and_already_scheduled():
    athlete = Athlete("omer", date(2026, 10, 5), date(2026, 12, 27))
    schedule = Schedule(athlete, "p", [
        _sw(1, date(2026, 10, 5), Discipline.RUN, 30, desc="easy run", status=WorkoutStatus.DONE),
        _sw(2, date(2026, 10, 6), Discipline.BIKE, 60, desc="tempo ride"),
        _sw(3, date(2026, 10, 7), Discipline.SWIM, 40, desc="easy swim"),
        _sw(4, date(2026, 10, 20), Discipline.RUN, 40, desc="later run"),
    ])
    garmin = FakeGarmin([{"itemType": "workout", "date": "2026-10-07", "title": "flexTri: easy swim"}])
    lines = push_schedule(schedule, garmin, date(2026, 10, 5), 7)
    assert garmin.scheduled == [(1, "2026-10-06")]
    assert lines == ["2026-10-06 flexTri: tempo ride: added", "2026-10-07 flexTri: easy swim: already on Garmin"]


def test_reads_schedule_from_web_app_database(tmp_path, monkeypatch, capsys):
    from flextri import garmin
    from flextri.storage import SqliteStore

    athlete = Athlete("omer", date(2026, 10, 5), date(2026, 12, 27))
    db = tmp_path / "flextri.db"
    SqliteStore(db).save(Schedule(athlete, "p", [_sw(1, date(2026, 10, 6), Discipline.RUN, 40, desc="easy run")]))
    fake = FakeGarmin()
    monkeypatch.setattr(garmin, "_login", lambda: fake)
    garmin.main(["--db", str(db), "--start", "2026-10-05"])
    assert "2026-10-06 flexTri: easy run: added" in capsys.readouterr().out
    assert fake.scheduled == [(1, "2026-10-06")]
