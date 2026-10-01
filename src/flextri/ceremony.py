"""Closing ceremony: summarize the whole block once race day arrives."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .models import Discipline, Schedule, WorkoutStatus

COUNTED = {WorkoutStatus.DONE, WorkoutStatus.PARTIAL, WorkoutStatus.MISSED}


@dataclass
class Summary:
    athlete: str
    plan: str
    sessions_planned: int
    sessions_done: int
    key_sessions_done: int
    key_sessions_total: int
    minutes_by_discipline: dict[str, int] = field(default_factory=dict)
    longest_streak_days: int = 0
    adaptations: int = 0

    @property
    def compliance(self) -> float:
        return self.sessions_done / self.sessions_planned if self.sessions_planned else 0.0

    def render(self) -> str:
        lines = [
            f"Race day, {self.athlete}! You finished {self.plan}.",
            f"Sessions completed: {self.sessions_done}/{self.sessions_planned} ({self.compliance:.0%})",
            f"Key sessions: {self.key_sessions_done}/{self.key_sessions_total}",
            f"Longest check-in streak: {self.longest_streak_days} days",
            f"Plan adapted {self.adaptations} times along the way",
        ]
        for disc, mins in sorted(self.minutes_by_discipline.items()):
            lines.append(f"  {disc}: {mins / 60:.1f} h")
        return "\n".join(lines)


def summarize(schedule: Schedule) -> Summary:
    training = [
        w for w in schedule.workouts
        if w.workout.discipline != Discipline.REST and w.status in COUNTED
    ]
    done = [w for w in training if w.status in (WorkoutStatus.DONE, WorkoutStatus.PARTIAL)]
    actual = {c.workout_id: c.actual_duration_min for c in schedule.checkins if c.workout_id}
    minutes: Counter[str] = Counter()
    for w in done:
        minutes[w.workout.discipline.value] += actual.get(w.id) or w.workout.duration_min

    days = sorted({c.date for c in schedule.checkins})
    streak = best = 0
    for i, d in enumerate(days):
        streak = streak + 1 if i and (d - days[i - 1]).days == 1 else 1
        best = max(best, streak)

    return Summary(
        athlete=schedule.athlete.name,
        plan=schedule.plan_name,
        sessions_planned=len(training),
        sessions_done=len(done),
        key_sessions_done=sum(w.workout.key for w in done),
        key_sessions_total=sum(w.workout.key for w in training),
        minutes_by_discipline=dict(minutes),
        longest_streak_days=best,
        adaptations=sum(len(w.adjustments) for w in schedule.workouts),
    )
