from datetime import date

import pytest

from flextri.models import Athlete, Phase, PlanTemplate, TemplateWeek
from flextri.scaling import build_schedule, fit_weeks, weeks_until


def _plan(phases):
    return PlanTemplate("t", [TemplateWeek(phase=p) for p in phases])


TWELVE = _plan([Phase.BASE] * 4 + [Phase.BUILD] * 4 + [Phase.PEAK] * 2 + [Phase.TAPER] * 2)


@pytest.mark.parametrize("n", [3, 6, 8, 12, 16, 24])
def test_fit_keeps_length_order_and_taper(n):
    weeks = fit_weeks(TWELVE, n)
    phases = [w.phase for w in weeks]
    assert len(weeks) == n
    assert phases == sorted(phases, key=[Phase.BASE, Phase.BUILD, Phase.PEAK, Phase.TAPER].index)
    assert phases[-2:] == [Phase.TAPER, Phase.TAPER]


def test_stretch_is_proportional():
    phases = [w.phase for w in fit_weeks(TWELVE, 22)]
    assert phases.count(Phase.BASE) == 8
    assert phases.count(Phase.BUILD) == 8
    assert phases.count(Phase.PEAK) == 4


def test_short_timeline_drops_earliest_phases():
    phases = [w.phase for w in fit_weeks(TWELVE, 3)]
    assert phases == [Phase.PEAK, Phase.TAPER, Phase.TAPER]


def test_weeks_until_counts_calendar_weeks():
    assert weeks_until(date(2026, 10, 5), date(2026, 10, 11)) == 1
    assert weeks_until(date(2026, 10, 5), date(2026, 12, 27)) == 12
    with pytest.raises(ValueError):
        weeks_until(date(2026, 10, 5), date(2026, 10, 1))


def test_schedule_respects_availability_and_dates(template):
    athlete = Athlete("omer", date(2026, 10, 7), date(2026, 12, 27), available_days={1, 2, 5, 6}, max_session_min=75)
    s = build_schedule(template, athlete)
    assert s.workouts
    assert all(athlete.start_date <= w.date <= athlete.race_date for w in s.workouts)
    assert all(w.date.weekday() in athlete.available_days for w in s.workouts)
    assert all(w.workout.duration_min <= 75 for w in s.workouts)
    assert s.workouts[-1].phase == Phase.TAPER
