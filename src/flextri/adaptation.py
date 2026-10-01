"""Daily check-in: record what the athlete actually did and adapt the next days.

Rules (deliberately simple and explainable; every change is logged on the workout):
1. Status: completed -> done, or partial if under 70% of the planned time; else missed.
2. A missed key session moves to the next free day within 3 days; easy sessions
   already on that day are dropped to make room. A missed easy session is let go.
3. High strain (fatigue or soreness >= 4, or RPE 3+ above what the zone expects)
   eases the next 2 days: 20% shorter and capped at zone 2.
4. Fatigue or soreness at 5 turns tomorrow into a rest day.
5. Three fresh check-ins in a row (done, RPE at or below expected, fatigue <= 2)
   add 5% to the next 3 days of easy sessions.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import CheckIn, Discipline, Schedule, ScheduledWorkout, WorkoutStatus

EXPECTED_RPE = {1: 3, 2: 4, 3: 6, 4: 8, 5: 9}
PARTIAL_RATIO = 0.7
RESCHEDULE_WINDOW_DAYS = 3


def _record(schedule: Schedule, checkin: CheckIn) -> ScheduledWorkout | None:
    schedule.checkins.append(checkin)
    if checkin.workout_id is None:
        return None
    sw = schedule.get(checkin.workout_id)
    if not checkin.completed:
        sw.status = WorkoutStatus.MISSED
    elif (
        checkin.actual_duration_min is not None
        and checkin.actual_duration_min < PARTIAL_RATIO * sw.workout.duration_min
    ):
        sw.status = WorkoutStatus.PARTIAL
    else:
        sw.status = WorkoutStatus.DONE
    return sw


def _is_training(sw: ScheduledWorkout) -> bool:
    return sw.workout.discipline != Discipline.REST and sw.status == WorkoutStatus.PLANNED


def _reschedule_key(schedule: Schedule, sw: ScheduledWorkout, today: date) -> list[str]:
    athlete = schedule.athlete
    for offset in range(1, RESCHEDULE_WINDOW_DAYS + 1):
        day = today + timedelta(days=offset)
        if day > athlete.race_date or day.weekday() not in athlete.available_days:
            continue
        that_day = [w for w in schedule.on(day) if _is_training(w)]
        if any(w.workout.key for w in that_day):
            continue
        for w in that_day:
            w.status = WorkoutStatus.DROPPED
            w.adjustments.append(f"dropped to make room for missed key session #{sw.id}")
        sw.date = day
        sw.status = WorkoutStatus.PLANNED
        sw.adjustments.append(f"missed on {today}, moved to {day}")
        return [f"Moved missed key session #{sw.id} to {day}"]
    sw.adjustments.append("missed, no free day to move it to")
    return [f"Could not fit missed key session #{sw.id} in the next {RESCHEDULE_WINDOW_DAYS} days"]


def _strained(schedule: Schedule, checkin: CheckIn, sw: ScheduledWorkout | None) -> bool:
    if checkin.fatigue >= 4 or checkin.soreness >= 4:
        return True
    if sw and checkin.rpe is not None:
        return checkin.rpe >= EXPECTED_RPE[sw.workout.intensity] + 3
    return False


def _fresh(schedule: Schedule, checkin: CheckIn) -> bool:
    if checkin.rpe is None or checkin.workout_id is None:
        return False
    sw = schedule.get(checkin.workout_id)
    return (
        sw.status == WorkoutStatus.DONE
        and checkin.rpe <= EXPECTED_RPE[sw.workout.intensity]
        and checkin.fatigue <= 2
    )


def apply_checkin(schedule: Schedule, checkin: CheckIn) -> list[str]:
    """Record a check-in and adapt upcoming workouts. Returns a list of changes."""
    changes: list[str] = []
    sw = _record(schedule, checkin)
    today = checkin.date

    if sw and sw.status == WorkoutStatus.MISSED and sw.workout.key:
        changes += _reschedule_key(schedule, sw, today)

    if checkin.fatigue >= 5 or checkin.soreness >= 5:
        for w in schedule.on(today + timedelta(days=1)):
            if _is_training(w):
                w.status = WorkoutStatus.DROPPED
                w.adjustments.append(f"rest day after check-in on {today}")
                changes.append(f"Dropped #{w.id} for a rest day")

    if _strained(schedule, checkin, sw):
        for w in schedule.upcoming(today, 2):
            if not _is_training(w) or any(a.startswith("eased") for a in w.adjustments):
                continue
            w.workout.duration_min = round(w.workout.duration_min * 0.8)
            w.workout.intensity = min(w.workout.intensity, 2)
            w.adjustments.append(f"eased after check-in on {today}")
            changes.append(f"Eased #{w.id} to {w.workout.duration_min} min, zone {w.workout.intensity}")

    recent = [c for c in schedule.checkins if c.workout_id is not None][-3:]
    if len(recent) == 3 and all(_fresh(schedule, c) for c in recent):
        for w in schedule.upcoming(today, 3):
            if not _is_training(w) or w.workout.key or any(a.startswith(("eased", "bumped")) for a in w.adjustments):
                continue
            w.workout.duration_min = round(w.workout.duration_min * 1.05)
            w.adjustments.append(f"bumped +5% after fresh streak ending {today}")
            changes.append(f"Bumped #{w.id} to {w.workout.duration_min} min")

    return changes
