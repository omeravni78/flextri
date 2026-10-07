"""What the athlete chooses to do on a calendar day: easier, swap, move, rest, add, undo.

Every action snapshots the workouts first so the last one can be undone, and is
logged as a DayAction. Each returns a plain list of what changed, for the banner.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import date, timedelta

from .adaptation import reschedule_key
from .models import DayAction, Discipline, Phase, Schedule, ScheduledWorkout, Workout, WorkoutStatus, nice_date
from .scaling import week_first_day
from .storage import _encode, workouts_from_list

EASIER_RATIO = 0.7
SWAPPABLE = (Discipline.SWIM, Discipline.BIKE, Discipline.RUN)
HISTORY_LIMIT = 20
BIG_EXTRA_MIN = 90


class ActionError(ValueError):
    """The action isn't allowed; the message is safe to show the athlete."""


def alternatives(workout: Workout) -> dict[str, list[Workout]]:
    """The choices the day panel offers for one session."""
    easier = copy.deepcopy(workout)
    easier.duration_min = round(workout.duration_min * EASIER_RATIO)
    easier.intensity = min(workout.intensity, 2)
    easier.description = f"easier {workout.description}".strip()
    swaps = []
    if not workout.key and workout.discipline in SWAPPABLE:
        for d in SWAPPABLE:
            if d != workout.discipline:
                swaps.append(Workout(d, workout.duration_min, workout.intensity, f"{d.value} instead of {workout.discipline.value}"))
    return {"easier": [easier], "swaps": swaps}


def snapshot(schedule: Schedule) -> None:
    """Remember the workouts (and check-ins) so the next change can be undone."""
    _snapshot(schedule)


def _snapshot(schedule: Schedule) -> None:
    schedule.history.append({
        "workouts": _encode([asdict(w) for w in schedule.workouts]),
        "actions": len(schedule.actions),
        "checkins": len(schedule.checkins),
    })
    del schedule.history[:-HISTORY_LIMIT]


def _planned(schedule: Schedule, workout_id: int) -> ScheduledWorkout:
    try:
        sw = schedule.get(workout_id)
    except KeyError:
        raise ActionError("That session no longer exists") from None
    if sw.status != WorkoutStatus.PLANNED:
        raise ActionError(f"{sw.label} is already {sw.status.value}")
    return sw


def _not_past(day: date, today: date) -> None:
    if day < today:
        raise ActionError("Past days only take a check-in")


def easier(schedule: Schedule, workout_id: int, today: date) -> list[str]:
    sw = _planned(schedule, workout_id)
    _not_past(sw.date, today)
    if any(a.startswith("easier version") for a in sw.adjustments):
        raise ActionError("This session is already the easier version")
    _snapshot(schedule)
    lighter = alternatives(sw.workout)["easier"][0]
    sw.workout.duration_min, sw.workout.intensity = lighter.duration_min, lighter.intensity
    sw.adjustments.append("easier version, chosen by you")
    schedule.actions.append(DayAction(sw.date, "easier", sw.id))
    return [f"{sw.label} is now {sw.workout.duration_min} min, zone {sw.workout.intensity}"]


def swap(schedule: Schedule, workout_id: int, discipline: Discipline, today: date) -> list[str]:
    sw = _planned(schedule, workout_id)
    _not_past(sw.date, today)
    if sw.workout.key:
        raise ActionError("Key sessions can be eased, moved or rested, but not swapped to another sport")
    if discipline not in SWAPPABLE or sw.workout.discipline not in SWAPPABLE or discipline == sw.workout.discipline:
        raise ActionError(f"Can't swap {sw.workout.discipline.value} to {discipline.value}")
    _snapshot(schedule)
    skipped = sw.workout.discipline
    sw.workout.discipline = discipline
    sw.workout.description = f"{discipline.value} instead of {skipped.value}"
    sw.adjustments.append(f"swapped from {skipped.value}, chosen by you")
    changes = [f"{nice_date(sw.date)} {skipped.value} swapped to {discipline.value}"]
    # Keep the weekly balance: the next easy session of the other sport gets the skipped one back.
    nxt = next(
        (w for w in sorted(schedule.upcoming(sw.date, 7), key=lambda w: w.date)
         if w.workout.discipline == discipline and not w.workout.key and w.id != sw.id),
        None,
    )
    if nxt:
        nxt.workout.discipline = skipped
        nxt.workout.description = f"{skipped.value} (balancing your swap on {sw.date})"
        nxt.adjustments.append(f"swapped to {skipped.value} to balance your swap on {nice_date(sw.date)}")
        changes.append(f"{nice_date(nxt.date)} {discipline.value} becomes {skipped.value} to keep the week balanced")
    schedule.actions.append(DayAction(sw.date, "swap", sw.id, discipline.value))
    return changes


def move(schedule: Schedule, workout_id: int, new_date: date, today: date) -> list[str]:
    sw = _planned(schedule, workout_id)
    _not_past(sw.date, today)
    _not_past(new_date, today)
    ws = schedule.athlete.week_start
    if week_first_day(new_date, ws) != week_first_day(sw.date, ws):
        raise ActionError("Sessions can only move within the same week")
    if new_date > schedule.athlete.race_date:
        raise ActionError("That's after race day")
    _snapshot(schedule)
    old = sw.date
    sw.date = new_date
    sw.adjustments.append(f"moved from {nice_date(old)} by you")
    changes = [f"{sw.workout.discipline.value.capitalize()} moved from {nice_date(old)} to {nice_date(new_date)}"]
    if sw.workout.key:
        for d in (new_date - timedelta(days=1), new_date + timedelta(days=1)):
            if any(w.workout.key and w.status == WorkoutStatus.PLANNED and w.id != sw.id for w in schedule.on(d)):
                changes.append(f"Heads up: key sessions on {nice_date(min(d, new_date))} and {nice_date(max(d, new_date))} are back to back")
    schedule.actions.append(DayAction(new_date, "move", sw.id, str(old)))
    return changes


def rest(schedule: Schedule, day: date, today: date) -> list[str]:
    _not_past(day, today)
    planned = [w for w in schedule.on(day) if w.status == WorkoutStatus.PLANNED and w.workout.discipline != Discipline.REST]
    if not planned:
        raise ActionError("Nothing planned that day")
    _snapshot(schedule)
    changes = []
    for w in planned:
        if w.workout.key:
            changes += reschedule_key(schedule, w, day)
            if w.date == day:  # no room found
                w.status = WorkoutStatus.DROPPED
        else:
            w.status = WorkoutStatus.DROPPED
            w.adjustments.append("rest day, chosen by you")
            changes.append(f"{w.label} dropped for rest")
    schedule.actions.append(DayAction(day, "rest"))
    return changes


def add(schedule: Schedule, day: date, workout: Workout, today: date) -> list[str]:
    if day > today:
        raise ActionError("Extra sessions are logged after you do them")
    _snapshot(schedule)
    sw = ScheduledWorkout(schedule.next_id(), day, workout, _phase_on(schedule, day), WorkoutStatus.DONE, ["added by you"])
    schedule.workouts.append(sw)
    changes = [f"Logged an extra {workout.discipline.value}, {workout.duration_min} min"]
    if workout.duration_min >= BIG_EXTRA_MIN or workout.intensity >= 4:
        for w in schedule.upcoming(day, 1):
            if w.workout.discipline != Discipline.REST and not any(a.startswith("eased") for a in w.adjustments):
                w.workout.duration_min = round(w.workout.duration_min * 0.8)
                w.workout.intensity = min(w.workout.intensity, 2)
                w.adjustments.append(f"eased after your extra session on {nice_date(day)}")
                changes.append(f"Eased {w.label} to {w.workout.duration_min} min, zone {w.workout.intensity}")
    schedule.actions.append(DayAction(day, "add", sw.id))
    return changes


def undo(schedule: Schedule) -> list[str]:
    if not schedule.history:
        raise ActionError("Nothing to undo")
    snap = schedule.history.pop()
    schedule.workouts = workouts_from_list(snap["workouts"])
    undone = schedule.actions[snap["actions"]:]
    del schedule.actions[snap["actions"]:]
    if "checkins" in snap:
        del schedule.checkins[snap["checkins"]:]
    return [f"Undid {a.kind} on {nice_date(a.date)}" for a in undone] or ["Undone"]


def _phase_on(schedule: Schedule, day: date) -> Phase:
    near = min(schedule.workouts, key=lambda w: abs((w.date - day).days), default=None)
    return near.phase if near else Phase.BASE
