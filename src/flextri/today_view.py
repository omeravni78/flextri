"""Shape a schedule into the Today screen (all three home-screen looks draw from this),
and turn a one-tap check-in into a CheckIn plus a before/after list of what changed."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .adaptation import EXPECTED_RPE
from .calendar_view import build_calendar
from .models import CheckIn, Discipline, Schedule, ScheduledWorkout, WorkoutStatus, nice_date

LOOKS = {
    "bigday": ("One Big Day", "One screen, one day: today's minutes big, the check-in under your thumb."),
    "lanes": ("Lane Lines", "Your week as pool lanes, each session drawn to its real length."),
    "chat": ("Coach Chat", "Your plan talks to you like a coach, and you answer with one tap."),
}
DEFAULT_LOOK = "bigday"

# One tap on the Today screen stands for a whole check-in form.
QUICK = {
    "good": "Done, felt good",
    "hard": "Done, felt hard",
    "short": "Cut it short",
    "skip": "Skipped it",
}

TITLES = {"long_ride": "Long ride", "long_run": "Long run", "brick": "Brick"}
_BRICK = re.compile(r"bike (\d+) min.*?run (\d+) min", re.IGNORECASE)


def title(w: ScheduledWorkout) -> str:
    return TITLES.get(w.workout.slot or "", w.workout.discipline.value.capitalize())


def brick_parts(description: str) -> list[tuple[str, int]] | None:
    """'bike 40 min (...) + run 20 min easy' -> [('bike', 40), ('run', 20)]."""
    m = _BRICK.search(description)
    return [("bike", int(m.group(1))), ("run", int(m.group(2)))] if m else None


def _session(w: ScheduledWorkout) -> dict:
    d = w.workout
    return {
        "id": w.id,
        "title": title(w),
        "discipline": d.discipline.value,
        "minutes": d.duration_min,
        "zone": d.intensity,
        "key": d.key,
        "description": d.description[:1].upper() + d.description[1:] if d.description else "",
        "status": w.status.value,
        "changed": bool(w.adjustments),
        "adjustments": w.adjustments,
        "parts": brick_parts(d.description) if d.discipline == Discipline.BRICK else None,
    }


def build_today(schedule: Schedule, today: date, day: date | None = None) -> dict:
    """Today's sessions, the current week, and the one session waiting for a check-in."""
    a = schedule.athlete
    around = a.start_date if today < a.start_date else today
    week = build_calendar(schedule, today, around, weeks=1)
    wk = week["weeks"][0]
    days = []
    for d in wk["days"]:
        dd = date.fromisoformat(d["date"])
        sessions = [_session(w) for w in sorted(schedule.on(dd), key=lambda w: w.id)
                    if w.workout.discipline != Discipline.REST]
        shown = [s for s in sessions if s["status"] != WorkoutStatus.DROPPED.value]
        days.append({
            "date": dd,
            "is_today": dd == today,
            "is_past": dd < today,
            "is_race_day": dd == a.race_date,
            "sessions": sessions,
            "minutes": sum(s["minutes"] for s in shown),
        })
    selected = day if day and any(d["date"] == day for d in days) else (today if any(d["is_today"] for d in days) else days[0]["date"])
    today_sessions = [w for w in sorted(schedule.on(today), key=lambda w: w.id)
                      if w.workout.discipline != Discipline.REST and w.status != WorkoutStatus.DROPPED]
    waiting = next((w for w in today_sessions if w.status == WorkoutStatus.PLANNED), None)
    yesterday = [_session(w) for w in sorted(schedule.on(today - timedelta(days=1)), key=lambda w: w.id)
                 if w.workout.discipline != Discipline.REST and w.status != WorkoutStatus.DROPPED]
    return {
        "athlete": a.name,
        "plan": schedule.plan_name,
        "today": today,
        "starts": a.start_date if today < a.start_date else None,
        "week_number": wk["number"],
        "total_weeks": week["total_weeks"],
        "phase": wk["phase"],
        "planned_min": wk["planned_min"],
        "done_min": wk["done_min"],
        "days": days,
        "selected": next(d for d in days if d["date"] == selected),
        "max_day_min": max([d["minutes"] for d in days] + [60]),
        "today_sessions": [_session(w) for w in today_sessions],
        "waiting": _session(waiting) if waiting else None,
        "yesterday": yesterday,
        "race_date": a.race_date,
        "days_to_race": (a.race_date - today).days,
        "finished": today >= a.race_date,
    }


def quick_checkin(sw: ScheduledWorkout, choice: str, today: date) -> CheckIn:
    """The check-in a one-tap answer stands for, tuned so the adaptation rules react as the words say."""
    expected = EXPECTED_RPE[sw.workout.intensity]
    planned = sw.workout.duration_min
    if choice == "good":
        return CheckIn(today, sw.id, True, planned, rpe=expected, fatigue=2, notes=QUICK[choice])
    if choice == "hard":
        return CheckIn(today, sw.id, True, planned, rpe=min(10, expected + 3), fatigue=4, notes=QUICK[choice])
    if choice == "short":
        return CheckIn(today, sw.id, True, round(planned * 0.5), rpe=expected, fatigue=3, notes=QUICK[choice])
    if choice == "skip":
        return CheckIn(today, sw.id, False, fatigue=3, notes=QUICK[choice])
    raise ValueError(f"unknown answer {choice!r}")


def snapshot(schedule: Schedule, today: date) -> dict[int, tuple]:
    return {w.id: (w.date, w.workout.discipline, w.workout.duration_min, w.workout.intensity, w.status)
            for w in schedule.workouts if w.date >= today}


def _fmt(w: tuple, name: str) -> str:
    _, _, minutes, zone, _ = w
    return f"{name} {minutes}′, zone {zone}"


def diff(schedule: Schedule, before: dict[int, tuple], today: date) -> list[dict]:
    """What the check-in changed in the days ahead, as before/after pairs for the screen."""
    out = []
    for w in sorted(schedule.workouts, key=lambda w: (w.date, w.id)):
        b = before.get(w.id)
        if b is None or w.date <= today and b[0] <= today:
            continue
        now = (w.date, w.workout.discipline, w.workout.duration_min, w.workout.intensity, w.status)
        if now == b:
            continue
        name = title(w)
        if w.status == WorkoutStatus.DROPPED and b[4] != WorkoutStatus.DROPPED:
            out.append({"day": nice_date(w.date), "before": _fmt(b, name), "after": "Dropped to make room"})
        elif w.date != b[0]:
            out.append({"day": nice_date(w.date), "before": f"Was on {nice_date(b[0])}", "after": f"{_fmt(now, name)}, moved here"})
        else:
            out.append({"day": nice_date(w.date), "before": _fmt(b, name), "after": _fmt(now, name)})
    return out


def summary(choice: str, sw: ScheduledWorkout, changes: list[dict], notes: list[str]) -> str:
    """One plain sentence on why the week did or didn't change."""
    if choice == "skip" and sw.workout.key:
        moved = next((c for c in changes if c["after"].endswith("moved here")), None)
        if moved:
            return f"{title(sw)} is a key session, so it moves to {moved['day']}."
        return notes[0] + "." if notes else "Logged."
    if choice == "hard" and changes:
        return "A hard session needs easier days after it, so the next two days get lighter."
    if choice == "good" and changes:
        return "Three fresh days in a row, so your next easy sessions grow a little."
    if choice == "short":
        return "Logged as partly done. The rest of the week stays as planned."
    if choice == "skip":
        return "Easy sessions can go when life happens. The rest of the week stays as planned."
    return "Nice work. The rest of the week stays as planned."
