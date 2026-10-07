"""Core data model: plan templates, the athlete's schedule, and check-ins."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


def nice_date(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


class Discipline(str, Enum):
    SWIM = "swim"
    BIKE = "bike"
    RUN = "run"
    BRICK = "brick"
    STRENGTH = "strength"
    REST = "rest"


class Phase(str, Enum):
    BASE = "base"
    BUILD = "build"
    PEAK = "peak"
    TAPER = "taper"


class WorkoutStatus(str, Enum):
    PLANNED = "planned"
    DONE = "done"
    PARTIAL = "partial"
    MISSED = "missed"
    DROPPED = "dropped"  # removed by adaptation


@dataclass
class Workout:
    """One session as written in a plan template."""

    discipline: Discipline
    duration_min: int
    intensity: int = 2  # training zone 1-5
    description: str = ""
    key: bool = False  # key sessions get rescheduled, not dropped, when missed
    slot: str | None = None  # in day-free plans: the role that decides its day (see SLOTS)


# Roles a session can have in a day-free plan. The athlete picks the day for the
# long ride, long run, brick and swims; the rest are spread over their training days.
SLOTS = ("swim", "long_ride", "long_run", "brick", "bike", "run", "strength", "pre_race", "race")


@dataclass
class TemplateWeek:
    phase: Phase
    # day index 0 (Mon) .. 6 (Sun) -> workouts that day (plans with fixed days)
    days: dict[int, list[Workout]] = field(default_factory=dict)
    # the week's sessions, each with a slot, when the plan leaves the days to the athlete
    sessions: list[Workout] = field(default_factory=list)

    @property
    def volume_min(self) -> int:
        return sum(w.duration_min for ws in self.days.values() for w in ws) + sum(w.duration_min for w in self.sessions)


@dataclass
class PlanTemplate:
    """A fixed-length plan as authored, e.g. a 12-week olympic plan."""

    name: str
    weeks: list[TemplateWeek]

    @property
    def length_weeks(self) -> int:
        return len(self.weeks)


class Experience(str, Enum):
    FIRST = "first"  # first triathlon
    SOME = "some"  # done a few
    EXPERIENCED = "experienced"


class Distance(str, Enum):
    SPRINT = "sprint"
    OLYMPIC = "olympic"
    HALF = "70.3"
    FULL = "full"


MONDAY, SUNDAY = 0, 6
WEEKEND = {5, 6}


@dataclass
class Athlete:
    """The athlete's profile: everything the onboarding wizard asks."""

    name: str
    start_date: date
    race_date: date
    available_days: set[int] = field(default_factory=lambda: set(range(7)))  # weekday numbers, 0 = Mon
    max_session_min: int | None = None  # applies to every day unless weekday/weekend limits are set
    week_start: int = MONDAY  # MONDAY or SUNDAY
    experience: Experience = Experience.SOME
    weekly_hours: float | None = None
    distance: Distance = Distance.OLYMPIC
    goal: str = "finish"  # "finish" or a target time such as "2:45:00"
    max_weekday_min: int | None = None
    max_weekend_min: int | None = None
    long_day: int | None = None  # weekday for the week's longest session
    pool_days: set[int] | None = None  # swim days; None = any training day
    long_ride_day: int | None = None
    long_run_day: int | None = None
    brick_day: int | None = None
    look: str = "bigday"  # home screen look: bigday, lanes or chat (see today_view.LOOKS)

    def limit_for(self, weekday: int) -> int | None:
        specific = self.max_weekend_min if weekday in WEEKEND else self.max_weekday_min
        return specific if specific is not None else self.max_session_min


@dataclass
class ScheduledWorkout:
    """A workout placed on a real calendar date for this athlete."""

    id: int
    date: date
    workout: Workout
    phase: Phase
    status: WorkoutStatus = WorkoutStatus.PLANNED
    adjustments: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """How the athlete refers to it, e.g. "Tue 6 Oct swim"."""
        return f"{nice_date(self.date)} {self.workout.discipline.value}"


@dataclass
class CheckIn:
    """What the athlete reports at the end of a day."""

    date: date
    workout_id: int | None = None
    completed: bool = True
    actual_duration_min: int | None = None
    rpe: int | None = None  # rate of perceived exertion 1-10
    fatigue: int = 3  # 1 fresh .. 5 exhausted
    soreness: int = 1  # 1 none .. 5 severe
    sleep_hours: float | None = None
    notes: str = ""


@dataclass
class DayAction:
    """A choice the athlete made on the calendar (easier, swap, move, rest, add)."""

    date: date
    kind: str
    workout_id: int | None = None
    detail: str = ""


@dataclass
class Schedule:
    athlete: Athlete
    plan_name: str
    workouts: list[ScheduledWorkout] = field(default_factory=list)
    checkins: list[CheckIn] = field(default_factory=list)
    actions: list[DayAction] = field(default_factory=list)
    template: PlanTemplate | None = None  # kept so the schedule can be rebuilt after a setup edit
    history: list[dict] = field(default_factory=list)  # snapshots for undo, newest last

    def next_id(self) -> int:
        return max((w.id for w in self.workouts), default=0) + 1

    def on(self, day: date) -> list[ScheduledWorkout]:
        return [w for w in self.workouts if w.date == day]

    def get(self, workout_id: int) -> ScheduledWorkout:
        for w in self.workouts:
            if w.id == workout_id:
                return w
        raise KeyError(workout_id)

    def upcoming(self, after: date, days: int) -> list[ScheduledWorkout]:
        return [
            w
            for w in self.workouts
            if after < w.date and (w.date - after).days <= days and w.status == WorkoutStatus.PLANNED
        ]
