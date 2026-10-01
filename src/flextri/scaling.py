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

from .models import Athlete, Discipline, Phase, PlanTemplate, ScheduledWorkout, Schedule, TemplateWeek

PHASE_ORDER = [Phase.BASE, Phase.BUILD, Phase.PEAK, Phase.TAPER]


def weeks_until(start: date, race: date) -> int:
    """Calendar weeks from the start week to the race week, inclusive."""
    if race < start:
        raise ValueError("race date is before start date")
    start_monday = start - timedelta(days=start.weekday())
    race_monday = race - timedelta(days=race.weekday())
    return (race_monday - start_monday).days // 7 + 1


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


def _place_day(day: int, available: set[int], used: dict[int, int]) -> int:
    """Pick the available weekday closest to `day`, preferring the least loaded."""
    if day in available:
        return day
    return min(available, key=lambda d: (abs(d - day), used.get(d, 0)))


def build_schedule(template: PlanTemplate, athlete: Athlete) -> Schedule:
    if not athlete.available_days:
        raise ValueError("athlete needs at least one available training day")
    n = weeks_until(athlete.start_date, athlete.race_date)
    weeks = fit_weeks(template, n)
    race_monday = athlete.race_date - timedelta(days=athlete.race_date.weekday())
    first_monday = race_monday - timedelta(weeks=n - 1)

    schedule = Schedule(athlete=athlete, plan_name=template.name)
    next_id = 1
    for i, week in enumerate(weeks):
        monday = first_monday + timedelta(weeks=i)
        used: dict[int, int] = {}
        for day in sorted(week.days):
            target = _place_day(day, athlete.available_days, used)
            when = monday + timedelta(days=target)
            if when < athlete.start_date or when > athlete.race_date:
                continue
            for workout in week.days[day]:
                if workout.discipline == Discipline.REST and target != day:
                    continue  # unavailable days already are rest days
                w = copy.deepcopy(workout)
                notes = []
                if target != day:
                    notes.append(f"moved from weekday {day} to {target} (availability)")
                if athlete.max_session_min and w.duration_min > athlete.max_session_min:
                    notes.append(f"capped {w.duration_min} -> {athlete.max_session_min} min")
                    w.duration_min = athlete.max_session_min
                schedule.workouts.append(
                    ScheduledWorkout(id=next_id, date=when, workout=w, phase=week.phase, adjustments=notes)
                )
                used[target] = used.get(target, 0) + 1
                next_id += 1
    return schedule
