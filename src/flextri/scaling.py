"""Stretch or compress a fixed-length plan template to the athlete's timeline.

Rules:
- The taper is kept as written, because it is what lands the athlete fresh on race day.
- The remaining weeks are shared between base/build/peak in proportion to how long
  each phase is in the template.
- Inside a phase, target week j maps to source week floor(j * source_len / target_len):
  stretching repeats weeks, compressing samples them, and the order is always kept.
- When there are too few weeks for every phase, the earliest phases are dropped first.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta

from .models import (
    Athlete, Discipline, Phase, PlanTemplate, ScheduledWorkout, Schedule, TemplateWeek, Workout, WorkoutStatus,
)

PHASE_ORDER = [Phase.BASE, Phase.BUILD, Phase.PEAK, Phase.TAPER]


def week_first_day(day: date, week_start: int = 0) -> date:
    """The first day of the calendar week containing `day` (week_start: 0 = Mon, 6 = Sun)."""
    return day - timedelta(days=(day.weekday() - week_start) % 7)


def weeks_until(start: date, race: date, week_start: int = 0) -> int:
    """Calendar weeks from the start week to the race week, inclusive."""
    if race < start:
        raise ValueError("race date is before start date")
    return (week_first_day(race, week_start) - week_first_day(start, week_start)).days // 7 + 1


def _group(template: PlanTemplate) -> dict[Phase, list[TemplateWeek]]:
    groups: dict[Phase, list[TemplateWeek]] = {p: [] for p in PHASE_ORDER}
    for week in template.weeks:
        groups[week.phase].append(week)
    return groups


def _allocate(lengths: dict[Phase, int], total: int) -> dict[Phase, int]:
    """Split `total` weeks across phases proportionally (largest remainder)."""
    phases = [p for p in PHASE_ORDER if lengths.get(p)]
    if total <= 0 or not phases:
        return {p: 0 for p in phases}
    if total < len(phases):
        # Not enough room for every phase: keep the latest ones, one week each.
        keep = phases[-total:]
        return {p: (1 if p in keep else 0) for p in phases}
    source_total = sum(lengths[p] for p in phases)
    # Every phase gets at least one week, the rest is shared proportionally.
    spare = total - len(phases)
    raw = {p: spare * lengths[p] / source_total for p in phases}
    alloc = {p: 1 + int(raw[p]) for p in phases}
    leftover = total - sum(alloc.values())
    for p in sorted(phases, key=lambda p: raw[p] - int(raw[p]), reverse=True)[:leftover]:
        alloc[p] += 1
    return alloc


def _resample(weeks: list[TemplateWeek], n: int) -> list[TemplateWeek]:
    return [copy.deepcopy(weeks[j * len(weeks) // n]) for j in range(n)]


def fit_weeks(template: PlanTemplate, target_weeks: int) -> list[TemplateWeek]:
    if target_weeks < 1:
        raise ValueError("target_weeks must be at least 1")
    groups = _group(template)
    taper = groups[Phase.TAPER][-target_weeks:] if target_weeks else []
    body = target_weeks - len(taper)
    alloc = _allocate({p: len(groups[p]) for p in PHASE_ORDER[:-1]}, body)
    fitted: list[TemplateWeek] = []
    for phase in PHASE_ORDER[:-1]:
        n = alloc.get(phase, 0)
        if n:
            fitted.extend(_resample(groups[phase], n))
    fitted.extend(copy.deepcopy(taper))
    return fitted


def _nearest(day: int, allowed: set[int], used: dict[int, int], week_start: int) -> int:
    """The allowed weekday closest to `day` inside the same week, preferring the least loaded."""
    if day in allowed:
        return day
    pos = lambda d: (d - week_start) % 7
    return min(allowed, key=lambda d: (abs(pos(d) - pos(day)), used.get(d, 0), pos(d)))


def _layout_week(week: TemplateWeek, athlete: Athlete) -> dict[int, list[tuple[Workout, list[str]]]]:
    """Map a template week's sessions onto the athlete's weekdays, with a note for every move."""
    placed: dict[int, list[tuple[Workout, list[str]]]] = {}
    used: dict[int, int] = {}
    for day in sorted(week.days):
        target = _nearest(day, athlete.available_days, used, athlete.week_start)
        for workout in week.days[day]:
            if workout.discipline == Discipline.REST and target != day:
                continue  # unavailable days already are rest days
            w, notes, where = copy.deepcopy(workout), [], target
            if w.discipline == Discipline.SWIM and athlete.pool_days is not None and where not in athlete.pool_days:
                pools = athlete.pool_days & athlete.available_days
                if pools:
                    where = _nearest(where, pools, used, athlete.week_start)
            if where != day:
                notes.append(f"moved from {DAY_NAMES[day]} to {DAY_NAMES[where]} (your week)")
            placed.setdefault(where, []).append((w, notes))
            used[where] = used.get(where, 0) + 1

    long_day = athlete.long_day
    if long_day is not None and long_day in athlete.available_days:
        training = [(d, w) for d, ws in placed.items() for w, _ in ws if w.discipline != Discipline.REST]
        if training:
            longest_day = max(training, key=lambda t: t[1].duration_min)[0]
            if longest_day != long_day:
                a, b = placed.pop(longest_day, []), placed.pop(long_day, [])
                for w, notes in a:
                    notes.append(f"long session on {DAY_NAMES[long_day]}")
                for w, notes in b:
                    notes.append(f"swapped to {DAY_NAMES[longest_day]} for your long day")
                if a:
                    placed[long_day] = a
                if b:
                    placed[longest_day] = b
    return placed


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _schedule_workouts(template: PlanTemplate, athlete: Athlete, first_id: int = 1) -> list[ScheduledWorkout]:
    if not athlete.available_days:
        raise ValueError("athlete needs at least one available training day")
    n = weeks_until(athlete.start_date, athlete.race_date, athlete.week_start)
    weeks = fit_weeks(template, n)
    first = week_first_day(athlete.race_date, athlete.week_start) - timedelta(weeks=n - 1)
    out: list[ScheduledWorkout] = []
    next_id = first_id
    for i, week in enumerate(weeks):
        week_first = first + timedelta(weeks=i)
        for weekday, items in sorted(_layout_week(week, athlete).items(), key=lambda kv: (kv[0] - athlete.week_start) % 7):
            when = week_first + timedelta(days=(weekday - athlete.week_start) % 7)
            if when < athlete.start_date or when > athlete.race_date:
                continue
            limit = athlete.limit_for(weekday)
            for w, notes in items:
                notes = list(notes)
                if limit and w.duration_min > limit:
                    notes.append(f"capped {w.duration_min} -> {limit} min")
                    w.duration_min = limit
                out.append(ScheduledWorkout(id=next_id, date=when, workout=w, phase=week.phase, adjustments=notes))
                next_id += 1
    return out


def build_schedule(template: PlanTemplate, athlete: Athlete) -> Schedule:
    return Schedule(
        athlete=athlete,
        plan_name=template.name,
        workouts=_schedule_workouts(template, athlete),
        template=copy.deepcopy(template),
    )


def _key(w: ScheduledWorkout) -> tuple:
    return (w.date, w.workout.discipline, w.workout.duration_min, w.workout.intensity)


def preview_rebuild(schedule: Schedule, athlete: Athlete, today: date) -> tuple[list[ScheduledWorkout], list[str]]:
    """What the future would look like with a new profile, and a plain list of what changes."""
    if schedule.template is None:
        raise ValueError("schedule has no template to rebuild from")
    athlete = copy.deepcopy(athlete)
    athlete.start_date = schedule.athlete.start_date  # the block started when it started
    fresh = [w for w in _schedule_workouts(schedule.template, athlete, schedule.next_id()) if w.date >= today]
    old = [w for w in schedule.workouts if w.date >= today and w.status == WorkoutStatus.PLANNED]

    changes = []
    old_weeks = weeks_until(schedule.athlete.start_date, schedule.athlete.race_date, schedule.athlete.week_start)
    new_weeks = weeks_until(athlete.start_date, athlete.race_date, athlete.week_start)
    if new_weeks != old_weeks:
        diff = new_weeks - old_weeks
        changes.append(f"{abs(diff)} week{'s' if abs(diff) != 1 else ''} {'added' if diff > 0 else 'removed'}")
    old_keys, new_keys = {_key(w) for w in old}, {_key(w) for w in fresh}
    added, removed = len(new_keys - old_keys), len(old_keys - new_keys)
    if added or removed:
        changes.append(f"{added} sessions new or changed, {removed} sessions replaced")
    if not changes:
        changes.append("No changes to your upcoming sessions")
    return fresh, changes


def rebuild(schedule: Schedule, athlete: Athlete, today: date) -> list[str]:
    """Apply a setup edit: past days and check-ins stay, today onward is re-planned."""
    fresh, changes = preview_rebuild(schedule, athlete, today)
    recorded = {WorkoutStatus.DONE, WorkoutStatus.PARTIAL, WorkoutStatus.MISSED}
    keep = [w for w in schedule.workouts if w.date < today or w.status in recorded]
    athlete = copy.deepcopy(athlete)
    athlete.start_date = schedule.athlete.start_date
    schedule.athlete = athlete
    schedule.workouts = sorted(keep + fresh, key=lambda w: (w.date, w.id))
    return changes
