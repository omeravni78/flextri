"""JSON persistence for templates and schedules (stdlib only, easy to swap for a DB)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from .models import (
    Athlete, CheckIn, DayAction, Discipline, Distance, Experience, Phase, PlanTemplate,
    Schedule, ScheduledWorkout, TemplateWeek, Workout, WorkoutStatus,
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
            days={int(day): [_workout(x) for x in ws] for day, ws in w.get("days", {}).items()},
            sessions=[_workout(x) for x in w.get("sessions", [])],
        )
        for w in d["weeks"]
    ]
    return PlanTemplate(name=d["name"], weeks=weeks)


def load_template(path: Path) -> PlanTemplate:
    return template_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def schedule_to_dict(s: Schedule) -> dict:
    return _encode(asdict(s))


def athlete_from_dict(a: dict) -> Athlete:
    return Athlete(
        name=a["name"],
        start_date=date.fromisoformat(a["start_date"]),
        race_date=date.fromisoformat(a["race_date"]),
        available_days=set(a["available_days"]),
        max_session_min=a.get("max_session_min"),
        week_start=a.get("week_start", 0),
        experience=Experience(a.get("experience", "some")),
        weekly_hours=a.get("weekly_hours"),
        distance=Distance(a.get("distance", "olympic")),
        goal=a.get("goal", "finish"),
        max_weekday_min=a.get("max_weekday_min"),
        max_weekend_min=a.get("max_weekend_min"),
        long_day=a.get("long_day"),
        pool_days=set(a["pool_days"]) if a.get("pool_days") is not None else None,
        long_ride_day=a.get("long_ride_day"),
        long_run_day=a.get("long_run_day"),
        brick_day=a.get("brick_day"),
        look=a.get("look", "bigday"),
    )


def athlete_to_dict(a: Athlete) -> dict:
    return _encode(asdict(a))


def workouts_from_list(items: list[dict]) -> list[ScheduledWorkout]:
    return [
        ScheduledWorkout(
            id=w["id"],
            date=date.fromisoformat(w["date"]),
            workout=_workout(w["workout"]),
            phase=Phase(w["phase"]),
            status=WorkoutStatus(w["status"]),
            adjustments=w["adjustments"],
        )
        for w in items
    ]


def schedule_from_dict(d: dict) -> Schedule:
    checkins = [CheckIn(**{**c, "date": date.fromisoformat(c["date"])}) for c in d["checkins"]]
    actions = [DayAction(**{**a, "date": date.fromisoformat(a["date"])}) for a in d.get("actions", [])]
    template = template_from_dict(d["template"]) if d.get("template") else None
    return Schedule(
        athlete=athlete_from_dict(d["athlete"]),
        plan_name=d["plan_name"],
        workouts=workouts_from_list(d["workouts"]),
        checkins=checkins,
        actions=actions,
        template=template,
        history=d.get("history", []),
    )


def save_schedule(s: Schedule, path: Path) -> None:
    Path(path).write_text(json.dumps(schedule_to_dict(s), indent=2), encoding="utf-8")


def load_schedule(path: Path) -> Schedule:
    return schedule_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class SqliteStore:
    """One athlete per install: the whole schedule is one JSON row in a local SQLite file."""

    def __init__(self, path: Path | str):
        import sqlite3

        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)")
        self.conn.commit()

    def load(self) -> Schedule | None:
        row = self.conn.execute("SELECT data FROM state WHERE id = 1").fetchone()
        return schedule_from_dict(json.loads(row[0])) if row else None

    def save(self, schedule: Schedule) -> None:
        data = json.dumps(schedule_to_dict(schedule))
        self.conn.execute("INSERT INTO state (id, data) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data", (data,))
        self.conn.commit()

    def clear(self) -> None:
        self.conn.execute("DELETE FROM state")
        self.conn.commit()
