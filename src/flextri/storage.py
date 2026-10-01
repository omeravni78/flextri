"""JSON persistence for templates and schedules (stdlib only, easy to swap for a DB)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from .models import (
    Athlete, CheckIn, Discipline, Phase, PlanTemplate, Schedule,
    ScheduledWorkout, TemplateWeek, Workout, WorkoutStatus,
)


def _encode(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, dict):
        return {str(k): _encode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_encode(v) for v in obj]
    return obj


def _workout(d: dict) -> Workout:
    return Workout(**{**d, "discipline": Discipline(d["discipline"])})


def template_from_dict(d: dict) -> PlanTemplate:
    weeks = [
        TemplateWeek(
            phase=Phase(w["phase"]),
            days={int(day): [_workout(x) for x in ws] for day, ws in w["days"].items()},
        )
        for w in d["weeks"]
    ]
    return PlanTemplate(name=d["name"], weeks=weeks)


def load_template(path: Path) -> PlanTemplate:
    return template_from_dict(json.loads(Path(path).read_text()))


def schedule_to_dict(s: Schedule) -> dict:
    return _encode(asdict(s))


def schedule_from_dict(d: dict) -> Schedule:
    a = d["athlete"]
    athlete = Athlete(
        name=a["name"],
        start_date=date.fromisoformat(a["start_date"]),
        race_date=date.fromisoformat(a["race_date"]),
        available_days=set(a["available_days"]),
        max_session_min=a.get("max_session_min"),
    )
    workouts = [
        ScheduledWorkout(
            id=w["id"],
            date=date.fromisoformat(w["date"]),
            workout=_workout(w["workout"]),
            phase=Phase(w["phase"]),
            status=WorkoutStatus(w["status"]),
            adjustments=w["adjustments"],
        )
        for w in d["workouts"]
    ]
    checkins = [CheckIn(**{**c, "date": date.fromisoformat(c["date"])}) for c in d["checkins"]]
    return Schedule(athlete=athlete, plan_name=d["plan_name"], workouts=workouts, checkins=checkins)


def save_schedule(s: Schedule, path: Path) -> None:
    Path(path).write_text(json.dumps(schedule_to_dict(s), indent=2))


def load_schedule(path: Path) -> Schedule:
    return schedule_from_dict(json.loads(Path(path).read_text()))
