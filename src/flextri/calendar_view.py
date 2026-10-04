"""Shape a schedule into the 4-week calendar the home screen draws."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from .actions import alternatives
from .models import Discipline, Schedule, ScheduledWorkout, WorkoutStatus
from .scaling import week_first_day, weeks_until

DONE = {WorkoutStatus.DONE, WorkoutStatus.PARTIAL}


def _session(w: ScheduledWorkout, today: date) -> dict:
    alts = alternatives(w.workout) if w.status == WorkoutStatus.PLANNED and w.date >= today else {"easier": [], "swaps": []}
    return {
        "id": w.id,
        "discipline": w.workout.discipline.value,
        "duration_min": w.workout.duration_min,
        "intensity": w.workout.intensity,
        "description": w.workout.description,
        "key": w.workout.key,
        "status": w.status.value,
        "changed": bool(w.adjustments),
        "adjustments": w.adjustments,
        "can_swap_to": [s.discipline.value for s in alts["swaps"]],
    }


def build_calendar(schedule: Schedule, today: date, around: date | None = None, weeks: int = 4) -> dict:
    """Current week plus the next weeks-1, starting on the athlete's chosen first weekday."""
    a = schedule.athlete
    first = week_first_day(around or today, a.week_start)
    total = weeks_until(a.start_date, a.race_date, a.week_start)
    block_first = week_first_day(a.race_date, a.week_start) - timedelta(weeks=total - 1)
    out = []
    for i in range(weeks):
        wk_first = first + timedelta(weeks=i)
        days, phases, planned_min, done_min = [], Counter(), 0, 0
        for d in range(7):
            day = wk_first + timedelta(days=d)
            sessions = sorted(schedule.on(day), key=lambda w: w.id)
            for w in sessions:
                if w.workout.discipline == Discipline.REST:
                    continue
                phases[w.phase.value] += 1
                if w.status != WorkoutStatus.DROPPED:
                    planned_min += w.workout.duration_min
                if w.status in DONE:
                    done_min += w.workout.duration_min
            days.append({
                "date": day.isoformat(),
                "weekday": day.weekday(),
                "is_today": day == today,
                "is_race_day": day == a.race_date,
                "editable": today <= day <= a.race_date,
                "sessions": [_session(w, today) for w in sessions],
            })
        number = (wk_first - block_first).days // 7 + 1
        out.append({
            "first_day": wk_first.isoformat(),
            "number": number if 1 <= number <= total else None,
            "phase": phases.most_common(1)[0][0] if phases else None,
            "planned_min": planned_min,
            "done_min": done_min,
            "days": days,
        })
    return {"athlete": a.name, "total_weeks": total, "week_start": a.week_start, "race_date": a.race_date.isoformat(), "weeks": out}
