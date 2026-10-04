"""JSON API behind the wizard and the calendar. Run: uvicorn flextri.web.api:app"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from .. import actions
from ..adaptation import apply_checkin
from ..calendar_view import build_calendar
from ..ceremony import summarize
from ..models import Athlete, CheckIn, Discipline, Distance, Experience, Workout
from ..scaling import build_schedule, preview_rebuild, rebuild, weeks_until
from ..storage import SqliteStore, athlete_to_dict, load_template

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = Path(os.environ.get("FLEXTRI_TEMPLATE", ROOT / "examples" / "placeholder_plan.json"))
DB_PATH = os.environ.get("FLEXTRI_DB", "flextri.db")

app = FastAPI(title="flexTri")
_store: SqliteStore | None = None


def get_store() -> SqliteStore:
    global _store
    if _store is None:
        _store = SqliteStore(DB_PATH)
    return _store


def get_today() -> date:
    return date.today()


class ProfileIn(BaseModel):
    """The wizard's answers."""

    name: str = Field(min_length=1)
    experience: Experience = Experience.SOME
    weekly_hours: float | None = Field(default=None, ge=0, le=40)
    race_date: date
    distance: Distance = Distance.OLYMPIC
    goal: str = "finish"
    start_date: date
    week_start: Literal[0, 6] = 0
    available_days: set[int] = Field(min_length=3)
    max_weekday_min: int | None = Field(default=None, gt=0)
    max_weekend_min: int | None = Field(default=None, gt=0)
    long_day: int | None = Field(default=None, ge=0, le=6)
    pool_days: set[int] | None = None

    @model_validator(mode="after")
    def check(self):
        if any(d not in range(7) for d in self.available_days | (self.pool_days or set())):
            raise ValueError("weekdays are 0 (Mon) to 6 (Sun)")
        if (self.race_date - self.start_date).days < 14:
            raise ValueError("the race must be at least 2 weeks after the start date")
        return self

    def to_athlete(self) -> Athlete:
        return Athlete(**self.model_dump())


class ActionIn(BaseModel):
    kind: Literal["easier", "swap", "move", "rest", "add"]
    workout_id: int | None = None
    discipline: Discipline | None = None
    new_date: date | None = None
    duration_min: int | None = Field(default=None, gt=0)
    intensity: int = Field(default=2, ge=1, le=5)


class CheckInIn(BaseModel):
    date: date
    workout_id: int | None = None
    completed: bool = True
    actual_duration_min: int | None = Field(default=None, ge=0)
    rpe: int | None = Field(default=None, ge=1, le=10)
    fatigue: int = Field(default=3, ge=1, le=5)
    soreness: int = Field(default=1, ge=1, le=5)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    notes: str = ""


def _fit_warning(p: ProfileIn) -> str | None:
    n = weeks_until(p.start_date, p.race_date, p.week_start)
    if n < 6:
        return f"Only {n} weeks: the plan will be squeezed hard"
    if n > 24:
        return f"{n} weeks is long: the plan will repeat a lot of weeks"
    return None


def _loaded(store: SqliteStore):
    schedule = store.load()
    if schedule is None:
        raise HTTPException(404, "No setup yet: finish the wizard first")
    return schedule


@app.get("/api/profile")
def get_profile(store: SqliteStore = Depends(get_store)):
    return athlete_to_dict(_loaded(store).athlete)


@app.post("/api/profile/preview")
def preview_profile(p: ProfileIn, store: SqliteStore = Depends(get_store), today: date = Depends(get_today)):
    """Step 4 of the wizard, and the 'what will change' screen when editing."""
    template = load_template(TEMPLATE_PATH)
    weeks = weeks_until(p.start_date, p.race_date, p.week_start)
    existing = store.load()
    changes = preview_rebuild(existing, p.to_athlete(), today)[1] if existing else []
    return {
        "plan": template.name,
        "plan_weeks": template.length_weeks,
        "fitted_weeks": weeks,
        "warning": _fit_warning(p),
        "changes": changes,
    }


@app.put("/api/profile")
def save_profile(p: ProfileIn, store: SqliteStore = Depends(get_store), today: date = Depends(get_today)):
    """Step 5 confirm, or 'Edit my setup' save. Past days never change."""
    existing = store.load()
    if existing is None:
        schedule = build_schedule(load_template(TEMPLATE_PATH), p.to_athlete())
        changes = [f"Plan fitted to {weeks_until(p.start_date, p.race_date, p.week_start)} weeks"]
    else:
        schedule, changes = existing, rebuild(existing, p.to_athlete(), today)
    store.save(schedule)
    return {"changes": changes, "warning": _fit_warning(p)}


@app.get("/api/calendar")
def calendar(around: date | None = None, store: SqliteStore = Depends(get_store), today: date = Depends(get_today)):
    return build_calendar(_loaded(store), today, around)


def perform_action(schedule, day: date, a: ActionIn, today: date) -> list[str]:
    """Run one calendar choice. Raises actions.ActionError with a message for the athlete."""
    if a.kind == "rest":
        return actions.rest(schedule, day, today)
    if a.kind == "add":
        if a.discipline is None or a.duration_min is None:
            raise actions.ActionError("An extra session needs a sport and a duration")
        return actions.add(schedule, day, Workout(a.discipline, a.duration_min, a.intensity, "extra session"), today)
    if a.workout_id is None:
        raise actions.ActionError("Pick a session")
    if a.kind == "easier":
        return actions.easier(schedule, a.workout_id, today)
    if a.kind == "swap":
        if a.discipline is None:
            raise actions.ActionError("Pick a sport to swap to")
        return actions.swap(schedule, a.workout_id, a.discipline, today)
    if a.new_date is None:
        raise actions.ActionError("Pick a day to move to")
    return actions.move(schedule, a.workout_id, a.new_date, today)


def check_checkin(schedule, c: CheckInIn, today: date) -> None:
    if c.date > today or (today - c.date).days > 2:
        raise actions.ActionError("Check-ins are for today or up to 2 days back")
    if c.workout_id is not None:
        try:
            schedule.get(c.workout_id)
        except KeyError:
            raise actions.ActionError(f"No session #{c.workout_id}") from None


@app.post("/api/days/{day}/actions")
def day_action(day: date, a: ActionIn, store: SqliteStore = Depends(get_store), today: date = Depends(get_today)):
    schedule = _loaded(store)
    try:
        changes = perform_action(schedule, day, a, today)
    except actions.ActionError as e:
        raise HTTPException(400, str(e)) from None
    store.save(schedule)
    return {"changes": changes}


@app.post("/api/undo")
def undo(store: SqliteStore = Depends(get_store)):
    schedule = _loaded(store)
    try:
        changes = actions.undo(schedule)
    except actions.ActionError as e:
        raise HTTPException(400, str(e)) from None
    store.save(schedule)
    return {"changes": changes}


@app.post("/api/checkins")
def checkin(c: CheckInIn, store: SqliteStore = Depends(get_store), today: date = Depends(get_today)):
    schedule = _loaded(store)
    try:
        check_checkin(schedule, c, today)
    except actions.ActionError as e:
        raise HTTPException(400, str(e)) from None
    changes = apply_checkin(schedule, CheckIn(**c.model_dump()))
    store.save(schedule)
    return {"changes": changes}


@app.get("/api/summary")
def summary(store: SqliteStore = Depends(get_store)):
    s = summarize(_loaded(store))
    return {**s.__dict__, "compliance": s.compliance}


from .ui import router as ui_router  # noqa: E402  (ui imports helpers defined above)

from fastapi.staticfiles import StaticFiles  # noqa: E402

app.include_router(ui_router)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
