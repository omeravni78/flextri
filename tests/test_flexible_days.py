"""Day-free plans: the athlete picks the days, the plan only says what to do each week."""

from datetime import date
from pathlib import Path

import pytest

from flextri.models import Athlete
from flextri.scaling import build_schedule
from flextri.storage import load_template

OLYMPIC = Path(__file__).parent.parent / "plans" / "olympic_8week_triathlete.json"
MON = date(2026, 10, 5)
RACE = date(2026, 11, 28)  # a Saturday, 8 weeks out


@pytest.fixture
def olympic():
    return load_template(OLYMPIC)


def _slots(schedule, slot):
    return [w for w in schedule.workouts if w.workout.slot == slot]


def test_plan_has_no_fixed_days(olympic):
    assert all(not w.days and w.sessions for w in olympic.weeks)
    assert all(s.slot for w in olympic.weeks for s in w.sessions)


def test_athlete_picks_the_days(olympic):
    athlete = Athlete("omer", MON, RACE, available_days={1, 2, 3, 4, 5, 6}, pool_days={2, 4},
                      long_ride_day=6, long_run_day=5, brick_day=3)
    s = build_schedule(olympic, athlete)
    race_week = RACE.isocalendar()[1]
    body = lambda ws: [w for w in ws if w.date.isocalendar()[1] != race_week]
    assert all(w.date.weekday() == 6 for w in body(_slots(s, "long_ride")))
    assert all(w.date.weekday() == 5 for w in body(_slots(s, "long_run")))
    assert all(w.date.weekday() == 3 for w in body(_slots(s, "brick")))
    assert all(w.date.weekday() in {2, 4} for w in _slots(s, "swim"))
    assert not any(w.date.weekday() == 0 for w in s.workouts)  # Monday is not a training day


def test_defaults_without_choices(olympic):
    s = build_schedule(olympic, Athlete("omer", MON, RACE))
    assert all(w.date.weekday() == 5 for w in _slots(s, "long_ride"))
    assert all(w.date.weekday() == 6 for w in _slots(s, "long_run"))


def test_race_week_ends_on_race_day(olympic):
    s = build_schedule(olympic, Athlete("omer", MON, RACE, long_run_day=6))
    assert [w.date for w in _slots(s, "race")] == [RACE]
    assert {w.date for w in _slots(s, "pre_race")} == {date(2026, 11, 27)}
    assert max(w.date for w in s.workouts) == RACE
    # the rest of race week sits before the shake-out day
    race_week = [w for w in s.workouts if w.date >= date(2026, 11, 23) and w.workout.slot not in ("race", "pre_race")]
    assert race_week and all(w.date < date(2026, 11, 27) for w in race_week)


def test_chosen_day_off_moves_with_a_note(olympic):
    athlete = Athlete("omer", MON, RACE, available_days={0, 1, 2, 3, 4, 5}, long_run_day=6)
    long_runs = _slots(build_schedule(olympic, athlete), "long_run")
    assert all(w.date.weekday() == 5 for w in long_runs)
    assert "outside your training days" in long_runs[0].adjustments[0]


def test_same_sport_is_spread_out(olympic):
    s = build_schedule(olympic, Athlete("omer", MON, RACE))
    first_week = [w for w in s.workouts if w.date < date(2026, 10, 12)]
    for day in {w.date for w in first_week}:
        sports = [w.workout.discipline.value for w in first_week if w.date == day and w.workout.discipline.value != "strength"]
        assert len(sports) == len(set(sports)), (day, sports)
