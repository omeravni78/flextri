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
    assert p["workoutName"] == "RUN tempo run"
    assert p["sportType"] == {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
    steps = p["workoutSegments"][0]["workoutSteps"]
    assert [s["stepType"]["stepTypeKey"] for s in steps] == ["warmup", "interval", "cooldown"]
    assert sum(s["endConditionValue"] for s in steps) == 40 * 60
    assert steps[1]["zoneNumber"] == 3


def test_swim_has_no_hr_target_and_short_session_is_one_step():
    [p] = to_garmin_workouts(_sw(1, date(2026, 10, 6), Discipline.SWIM, 15))
    [step] = p["workoutSegments"][0]["workoutSteps"]
    assert step["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert "zoneNumber" not in step
    # id 3 is Garmin's "other" sport, which is why swims used to look like everything else
    assert p["sportType"] == {"sportTypeId": 4, "sportTypeKey": "swimming", "displayOrder": 3}
    assert p["poolLength"] == 25.0
    assert p["workoutName"] == "SWIM swim"


def test_brick_splits_into_ride_and_run_rest_is_skipped():
    bike, run = to_garmin_workouts(_sw(1, date(2026, 10, 6), Discipline.BRICK, 90, desc="brick"))
    assert (bike["estimatedDurationInSecs"], run["estimatedDurationInSecs"]) == (60 * 60, 30 * 60)
    assert (bike["workoutName"], run["workoutName"]) == ("BIKE brick", "RUN brick")
    assert bike["sportType"]["sportTypeKey"] == "cycling"
    assert to_garmin_workouts(_sw(2, date(2026, 10, 6), Discipline.REST, 0)) == []


def test_push_window_skips_done_and_already_scheduled():
    athlete = Athlete("omer", date(2026, 10, 5), date(2026, 12, 27))
    schedule = Schedule(athlete, "p", [
        _sw(1, date(2026, 10, 5), Discipline.RUN, 30, desc="easy run", status=WorkoutStatus.DONE),
        _sw(2, date(2026, 10, 6), Discipline.BIKE, 60, desc="tempo ride"),
        _sw(3, date(2026, 10, 7), Discipline.SWIM, 40, desc="easy swim"),
        _sw(4, date(2026, 10, 20), Discipline.RUN, 40, desc="later run"),
    ])
    garmin = FakeGarmin([{"itemType": "workout", "date": "2026-10-07", "title": "SWIM easy swim"}])
    lines = push_schedule(schedule, garmin, date(2026, 10, 5), 7)
    assert garmin.scheduled == [(1, "2026-10-06")]
    assert lines == ["2026-10-06 BIKE tempo ride: added", "2026-10-07 SWIM easy swim: already on Garmin"]


def test_reads_schedule_from_web_app_database(tmp_path, monkeypatch, capsys):
    from flextri import garmin
    from flextri.storage import SqliteStore

    athlete = Athlete("omer", date(2026, 10, 5), date(2026, 12, 27))
    db = tmp_path / "flextri.db"
    SqliteStore(db).save(Schedule(athlete, "p", [_sw(1, date(2026, 10, 6), Discipline.RUN, 40, desc="easy run")]))
    fake = FakeGarmin()
    monkeypatch.setattr(garmin, "_login", lambda: fake)
    garmin.main(["--db", str(db), "--start", "2026-10-05"])
    assert "2026-10-06 RUN easy run: added" in capsys.readouterr().out
    assert fake.scheduled == [(1, "2026-10-06")]


def test_export_writes_one_json_file_per_workout(tmp_path):
    import json

    from flextri.garmin import export_schedule

    athlete = Athlete("omer", date(2026, 10, 5), date(2026, 12, 27))
    schedule = Schedule(athlete, "p", [
        _sw(1, date(2026, 10, 6), Discipline.BRICK, 90, desc="Race-pace brick"),
        _sw(2, date(2026, 10, 7), Discipline.REST, 0),
    ])
    paths = export_schedule(schedule, tmp_path / "out", date(2026, 10, 5), 7)
    assert [p.name for p in paths] == ["2026-10-06_bike-race-pace-brick.json", "2026-10-06_run-race-pace-brick.json"]
    assert json.loads(paths[0].read_text())["sportType"]["sportTypeKey"] == "cycling"


def test_test_mode_sends_one_easy_run_without_a_plan(tmp_path, monkeypatch, capsys):
    from flextri import garmin

    fake = FakeGarmin()
    monkeypatch.setattr(garmin, "_login", lambda: fake)
    garmin.main(["--test", "--db", str(tmp_path / "missing.db"), "--start", "2026-10-05"])
    assert capsys.readouterr().out.strip() == "2026-10-05 RUN test run: added"
    assert fake.uploaded[0]["estimatedDurationInSecs"] == 20 * 60


def test_names_fit_garmins_32_characters_and_keep_the_full_text_in_the_description():
    [p] = to_garmin_workouts(_sw(1, date(2026, 10, 6), Discipline.RUN, 40, 2, "easy with 8x30s hill strides and drills"))
    assert p["workoutName"] == "RUN easy with 8x30s hill strides"
    assert len(p["workoutName"]) <= 32
    assert p["description"].startswith("easy with 8x30s hill strides and drills · Zone 2")


def test_brick_names_take_each_sports_part():
    bike, run = to_garmin_workouts(_sw(1, date(2026, 10, 6), Discipline.BRICK, 60, 3,
                                       "bike 40 min (12x15s fast/45s easy) + run 20 min easy off the bike"))
    assert bike["workoutName"] == "BIKE brick 40 min (12x15s"
    assert run["workoutName"] == "RUN brick 20 min easy off the"


def test_push_remembers_the_workouts_it_created():
    from flextri.garmin import is_flextri, sent_ids

    athlete = Athlete("omer", date(2026, 10, 5), date(2026, 12, 27))
    schedule = Schedule(athlete, "p", [_sw(1, date(2026, 10, 6), Discipline.RUN, 30, desc="easy run")])
    push_schedule(schedule, FakeGarmin(), date(2026, 10, 5), 7)
    assert sent_ids() == {1}
    assert is_flextri("RUN easy run", 1, sent_ids())
    assert is_flextri("flexTri: easy run")  # sent before ids were saved
    assert not is_flextri("Morning run", 2, sent_ids())
