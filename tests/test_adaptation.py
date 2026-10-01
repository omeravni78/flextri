from datetime import date, timedelta

import pytest

from flextri.adaptation import apply_checkin
from flextri.ceremony import summarize
from flextri.models import Athlete, CheckIn, Discipline, WorkoutStatus
from flextri.scaling import build_schedule
from flextri.storage import schedule_from_dict, schedule_to_dict

MON = date(2026, 10, 5)


@pytest.fixture
def schedule(template):
    return build_schedule(template, Athlete("omer", MON, MON + timedelta(weeks=8, days=6)))


def _first(schedule, day, discipline):
    return next(w for w in schedule.on(day) if w.workout.discipline == discipline)


def test_completed_and_partial(schedule):
    swim = _first(schedule, MON + timedelta(days=1), Discipline.SWIM)
    apply_checkin(schedule, CheckIn(swim.date, swim.id, actual_duration_min=10, rpe=4))
    assert swim.status == WorkoutStatus.PARTIAL


def test_missed_key_session_moves_forward(schedule):
    tempo = _first(schedule, MON + timedelta(days=2), Discipline.BIKE)
    easy_run = _first(schedule, MON + timedelta(days=3), Discipline.RUN)
    changes = apply_checkin(schedule, CheckIn(tempo.date, tempo.id, completed=False))
    assert tempo.date == MON + timedelta(days=3)
    assert tempo.status == WorkoutStatus.PLANNED
    assert easy_run.status == WorkoutStatus.DROPPED
    assert changes


def test_missed_easy_session_is_let_go(schedule):
    swim = _first(schedule, MON + timedelta(days=1), Discipline.SWIM)
    before = [(w.id, w.date, w.status) for w in schedule.workouts if w.id != swim.id]
    assert apply_checkin(schedule, CheckIn(swim.date, swim.id, completed=False)) == []
    assert before == [(w.id, w.date, w.status) for w in schedule.workouts if w.id != swim.id]


def test_high_strain_eases_next_two_days_once(schedule):
    swim = _first(schedule, MON + timedelta(days=1), Discipline.SWIM)
    tempo = _first(schedule, MON + timedelta(days=2), Discipline.BIKE)
    planned = tempo.workout.duration_min
    apply_checkin(schedule, CheckIn(swim.date, swim.id, rpe=9, fatigue=4))
    assert tempo.workout.intensity == 2
    assert tempo.workout.duration_min == round(planned * 0.8)
    apply_checkin(schedule, CheckIn(swim.date, None, fatigue=4))
    assert tempo.workout.duration_min == round(planned * 0.8)


def test_exhaustion_makes_tomorrow_rest(schedule):
    swim = _first(schedule, MON + timedelta(days=1), Discipline.SWIM)
    apply_checkin(schedule, CheckIn(swim.date, swim.id, fatigue=5))
    assert all(w.status == WorkoutStatus.DROPPED for w in schedule.on(MON + timedelta(days=2)))


def test_fresh_streak_bumps_easy_sessions(schedule):
    week2 = MON + timedelta(weeks=1)
    easy_run = _first(schedule, week2 + timedelta(days=3), Discipline.RUN)
    planned = easy_run.workout.duration_min
    for d, disc in [(-2, Discipline.BIKE), (-1, Discipline.RUN), (1, Discipline.SWIM)]:
        day = week2 + timedelta(days=d)
        w = _first(schedule, day, disc)
        apply_checkin(schedule, CheckIn(day, w.id, rpe=3, fatigue=2))
    assert easy_run.workout.duration_min == round(planned * 1.05)


def test_roundtrip_and_ceremony(schedule):
    swim = _first(schedule, MON + timedelta(days=1), Discipline.SWIM)
    tempo = _first(schedule, MON + timedelta(days=2), Discipline.BIKE)
    apply_checkin(schedule, CheckIn(swim.date, swim.id, actual_duration_min=45, rpe=4, fatigue=2))
    apply_checkin(schedule, CheckIn(tempo.date, tempo.id, rpe=6, fatigue=3))
    restored = schedule_from_dict(schedule_to_dict(schedule))
    assert restored == schedule
    summary = summarize(restored)
    assert summary.sessions_done == 2
    assert summary.longest_streak_days == 2
    assert summary.minutes_by_discipline["swim"] == 45
    assert "omer" in summary.render()
