from datetime import date, timedelta

from flextri.models import Athlete, Discipline, WorkoutStatus
from flextri.scaling import build_schedule, rebuild, week_first_day, weeks_until

SUN = date(2026, 10, 4)


def test_week_first_day_follows_week_start():
    wed = date(2026, 10, 7)
    assert week_first_day(wed, 0) == date(2026, 10, 5)
    assert week_first_day(wed, 6) == SUN
    # Sunday race: its own week when weeks start Sunday, the end of a week when they start Monday.
    assert weeks_until(date(2026, 10, 5), date(2026, 10, 11), 0) == 1
    assert weeks_until(date(2026, 10, 5), date(2026, 10, 11), 6) == 2


def test_sunday_start_keeps_weekdays(template):
    athlete = Athlete("omer", SUN, SUN + timedelta(weeks=8), week_start=6)
    s = build_schedule(template, athlete)
    # The template's Wednesday tempo ride stays on a Wednesday.
    tempo = [w for w in s.workouts if w.workout.description == "tempo ride"]
    assert tempo and all(w.date.weekday() == 2 for w in tempo)
    assert s.workouts[0].date >= SUN


def test_pool_days_long_day_and_limits(template):
    athlete = Athlete(
        "omer", date(2026, 10, 5), date(2026, 12, 27),
        available_days={0, 1, 2, 3, 5, 6}, pool_days={3}, long_day=6,
        max_weekday_min=50, max_weekend_min=100,
    )
    s = build_schedule(template, athlete)
    swims = [w for w in s.workouts if w.workout.discipline == Discipline.SWIM]
    assert swims and all(w.date.weekday() == 3 for w in swims)
    for wk in {week_first_day(w.date, 0) for w in s.workouts}:
        week = [w for w in s.workouts if week_first_day(w.date, 0) == wk and w.workout.discipline != Discipline.REST]
        assert max(week, key=lambda w: w.workout.duration_min).date.weekday() == 6
    assert all(w.workout.duration_min <= (100 if w.date.weekday() >= 5 else 50) for w in s.workouts)


def test_rebuild_keeps_past_and_refits_future(template):
    athlete = Athlete("omer", date(2026, 10, 5), date(2026, 12, 27))
    s = build_schedule(template, athlete)
    today = date(2026, 10, 19)
    past = [w for w in s.workouts if w.date < today]
    past[1].status = WorkoutStatus.DONE

    later = Athlete("omer", date(2026, 10, 5), date(2027, 1, 10), available_days={1, 2, 3, 5, 6})
    changes = rebuild(s, later, today)

    assert changes[0] == "2 weeks added"
    assert [w for w in s.workouts if w.date < today] == past
    future = [w for w in s.workouts if w.date >= today]
    assert all(w.date.weekday() in later.available_days for w in future)
    assert max(w.date for w in s.workouts) <= date(2027, 1, 10)
    assert len({w.id for w in s.workouts}) == len(s.workouts)
    assert s.athlete.race_date == date(2027, 1, 10)


def test_rebuild_with_same_profile_changes_nothing(template):
    athlete = Athlete("omer", date(2026, 10, 5), date(2026, 12, 27))
    s = build_schedule(template, athlete)
    assert rebuild(s, athlete, date(2026, 10, 19)) == ["No changes to your upcoming sessions"]
