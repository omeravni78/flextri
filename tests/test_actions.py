from datetime import date, timedelta

import pytest

from flextri import actions
from flextri.models import Athlete, Discipline, Workout, WorkoutStatus
from flextri.scaling import build_schedule
from flextri.storage import schedule_from_dict, schedule_to_dict

MON = date(2026, 10, 5)


@pytest.fixture
def schedule(template):
    return build_schedule(template, Athlete("omer", MON, MON + timedelta(weeks=8, days=6)))


def _on(schedule, offset, discipline):
    return next(w for w in schedule.on(MON + timedelta(days=offset)) if w.workout.discipline == discipline)


def test_alternatives_respect_key_sessions():
    easy = Workout(Discipline.RUN, 40, 2, "easy run")
    key = Workout(Discipline.BIKE, 60, 3, "tempo", key=True)
    assert [w.discipline for w in actions.alternatives(easy)["swaps"]] == [Discipline.SWIM, Discipline.BIKE]
    assert actions.alternatives(key)["swaps"] == []
    assert actions.alternatives(key)["easier"][0].duration_min == 42


def test_easier_then_undo(schedule):
    tempo = _on(schedule, 2, Discipline.BIKE)
    actions.easier(schedule, tempo.id, MON)
    assert (tempo.workout.duration_min, tempo.workout.intensity) == (42, 2)
    with pytest.raises(actions.ActionError):
        actions.easier(schedule, tempo.id, MON)
    actions.undo(schedule)
    restored = schedule.get(tempo.id)
    assert (restored.workout.duration_min, restored.workout.intensity) == (60, 3)
    assert schedule.actions == []


def test_swap_easy_only_and_balances_week(schedule):
    with pytest.raises(actions.ActionError, match="Key sessions"):
        actions.swap(schedule, _on(schedule, 2, Discipline.BIKE).id, Discipline.RUN, MON)
    swim = _on(schedule, 1, Discipline.SWIM)
    run = _on(schedule, 3, Discipline.RUN)
    changes = actions.swap(schedule, swim.id, Discipline.RUN, MON)
    assert swim.workout.discipline == Discipline.RUN
    assert run.workout.discipline == Discipline.SWIM
    assert len(changes) == 2


def test_move_within_week_and_warns_on_back_to_back_keys(schedule):
    tempo = _on(schedule, 2, Discipline.BIKE)
    changes = actions.move(schedule, tempo.id, MON + timedelta(days=4), MON)
    assert tempo.date == MON + timedelta(days=4)
    assert any("back to back" in c for c in changes)
    with pytest.raises(actions.ActionError, match="same week"):
        actions.move(schedule, tempo.id, MON + timedelta(days=8), MON)
    with pytest.raises(actions.ActionError, match="Past"):
        actions.move(schedule, tempo.id, MON + timedelta(days=3), MON + timedelta(days=5))


def test_rest_moves_key_and_drops_easy(schedule):
    tempo = _on(schedule, 2, Discipline.BIKE)
    swim = _on(schedule, 1, Discipline.SWIM)
    actions.rest(schedule, MON + timedelta(days=2), MON)
    assert tempo.date == MON + timedelta(days=3) and tempo.status == WorkoutStatus.PLANNED
    actions.rest(schedule, MON + timedelta(days=1), MON)
    assert swim.status == WorkoutStatus.DROPPED


def test_add_big_extra_eases_tomorrow(schedule):
    day = MON + timedelta(days=1)
    tempo = _on(schedule, 2, Discipline.BIKE)
    actions.add(schedule, day, Workout(Discipline.BIKE, 120, 2, "group ride"), day)
    assert tempo.workout.duration_min == 48
    with pytest.raises(actions.ActionError):
        actions.add(schedule, day + timedelta(days=1), Workout(Discipline.RUN, 30), day)


def test_actions_survive_roundtrip(schedule):
    actions.easier(schedule, _on(schedule, 2, Discipline.BIKE).id, MON)
    restored = schedule_from_dict(schedule_to_dict(schedule))
    assert restored == schedule
    actions.undo(restored)
    assert restored.get(_on(schedule, 2, Discipline.BIKE).id).workout.duration_min == 60
