"""HTML screens (Jinja + HTMX): the onboarding wizard, the 4-week calendar and the day panel."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from .. import actions
from ..adaptation import apply_checkin
from ..calendar_view import build_calendar
from ..ceremony import summarize
from ..models import CheckIn, Discipline
from ..scaling import build_schedule, fit_weeks, preview_rebuild, rebuild, week_first_day, weeks_until
from ..storage import SqliteStore, load_template
from . import api

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PHASES = ["base", "build", "peak", "taper"]


def _fmt_day(value: str | date, pattern: str = "%a %d %b") -> str:
    d = date.fromisoformat(value) if isinstance(value, str) else value
    return d.strftime(pattern)


templates.env.filters["day"] = _fmt_day
templates.env.globals["DAY_NAMES"] = DAY_NAMES
templates.env.filters["daynames"] = lambda days, ordered: ", ".join(DAY_NAMES[d] for d in ordered if d in days)


def _ordered_days(week_start: int) -> list[int]:
    return [(week_start + i) % 7 for i in range(7)]


def _profile_from_form(form) -> tuple[api.ProfileIn | None, list[str]]:
    """Turn the wizard's form fields into a ProfileIn, or a list of readable errors."""
    def opt_int(key):
        v = form.get(key)
        return int(v) if v not in (None, "") else None

    data = {
        "name": form.get("name", "").strip(),
        "experience": form.get("experience") or "some",
        "weekly_hours": float(form["weekly_hours"]) if form.get("weekly_hours") else None,
        "race_date": form.get("race_date") or None,
        "distance": form.get("distance") or "olympic",
        "goal": (form.get("goal") or "finish").strip() or "finish",
        "start_date": form.get("start_date") or None,
        "week_start": int(form.get("week_start") or 0),
        "available_days": [int(d) for d in form.getlist("available_days")],
        "max_weekday_min": opt_int("max_weekday_min"),
        "max_weekend_min": opt_int("max_weekend_min"),
        "long_day": opt_int("long_day"),
        "pool_days": [int(d) for d in form.getlist("pool_days")] or None,
    }
    try:
        return api.ProfileIn(**data), []
    except ValidationError as e:
        return None, [_readable(err) for err in e.errors()]


def _readable(err: dict) -> str:
    field = ".".join(str(x) for x in err.get("loc", []) if x != "__root__")
    msg = err.get("msg", "").removeprefix("Value error, ")
    names = {
        "name": "Your name", "race_date": "Race date", "start_date": "Start date",
        "available_days": "Training days", "weekly_hours": "Training hours",
    }
    if field == "available_days" and "at least" in msg:
        return "Pick at least 3 training days"
    label = names.get(field)
    return f"{label}: {msg}" if label else msg[:1].upper() + msg[1:]


def _phase_bar(n: int) -> list[dict]:
    weeks = fit_weeks(load_template(api.TEMPLATE_PATH), n)
    counts = Counter(w.phase.value for w in weeks)
    return [{"phase": p, "weeks": counts[p]} for p in PHASES if counts[p]]


def _banner(changes: list[str], error: bool = False) -> dict:
    return {"items": changes, "error": error}


def _calendar_ctx(store: SqliteStore, today: date, around: date | None = None, banner: dict | None = None) -> dict:
    schedule = store.load()
    cal = build_calendar(schedule, today, around)
    first = date.fromisoformat(cal["weeks"][0]["first_day"])
    return {
        "cal": cal,
        "today": today,
        "prev": (first - timedelta(weeks=1)).isoformat(),
        "next": (first + timedelta(weeks=1)).isoformat(),
        "around": first.isoformat(),
        "banner": banner,
        "can_undo": bool(schedule.history),
        "finished": today >= schedule.athlete.race_date,
    }


def _day_ctx(store: SqliteStore, day: date, today: date) -> dict:
    schedule = store.load()
    cal = build_calendar(schedule, today, day, weeks=1)
    info = next(d for d in cal["weeks"][0]["days"] if d["date"] == day.isoformat())
    ws = schedule.athlete.week_start
    first = week_first_day(day, ws)
    move_to = [
        first + timedelta(days=i) for i in range(7)
        if first + timedelta(days=i) != day and today <= first + timedelta(days=i) <= schedule.athlete.race_date
    ]
    return {
        "day": day,
        "info": info,
        "today": today,
        "move_to": move_to,
        "can_checkin": 0 <= (today - day).days <= 2,
        "can_add": day <= today,
        "sports": [d.value for d in (Discipline.SWIM, Discipline.BIKE, Discipline.RUN, Discipline.STRENGTH)],
    }


# ---------- wizard ----------

@router.get("/setup", response_class=HTMLResponse)
def setup(request: Request, store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    schedule = store.load()
    a = schedule.athlete if schedule else None
    next_week_start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)  # next Monday
    values = {
        "name": a.name if a else "",
        "experience": a.experience.value if a else "some",
        "weekly_hours": a.weekly_hours if a and a.weekly_hours is not None else "",
        "race_date": a.race_date.isoformat() if a else "",
        "distance": a.distance.value if a else "olympic",
        "goal": a.goal if a else "finish",
        "start_date": a.start_date.isoformat() if a else next_week_start.isoformat(),
        "week_start": a.week_start if a else 0,
        "available_days": sorted(a.available_days) if a else [1, 2, 3, 5, 6],
        "max_weekday_min": a.max_weekday_min or "" if a else "",
        "max_weekend_min": a.max_weekend_min or "" if a else "",
        "long_day": a.long_day if a and a.long_day is not None else "",
        "pool_days": sorted(a.pool_days) if a and a.pool_days is not None else [],
    }
    return templates.TemplateResponse(request, "wizard.html", {"v": values, "editing": a is not None})


@router.post("/ui/preview", response_class=HTMLResponse)
async def preview(request: Request, store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    profile, errors = _profile_from_form(await request.form())
    if errors:
        return templates.TemplateResponse(request, "_preview.html", {"errors": errors})
    template = load_template(api.TEMPLATE_PATH)
    athlete = profile.to_athlete()
    n = weeks_until(athlete.start_date, athlete.race_date, athlete.week_start)
    existing = store.load()
    changes = preview_rebuild(existing, athlete, today)[1] if existing else []
    draft = build_schedule(template, athlete)
    mini = build_calendar(draft, today, max(athlete.start_date, today) if existing else athlete.start_date, weeks=2)
    return templates.TemplateResponse(request, "_preview.html", {
        "errors": [],
        "p": profile,
        "plan": template.name,
        "plan_weeks": template.length_weeks,
        "weeks": n,
        "bar": _phase_bar(n),
        "warning": api._fit_warning(profile),
        "changes": changes,
        "mini": mini,
        "ordered": _ordered_days(athlete.week_start),
    })


@router.post("/setup")
async def save_setup(request: Request, store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    form = await request.form()
    profile, errors = _profile_from_form(form)
    if errors:
        return templates.TemplateResponse(request, "_preview.html", {"errors": errors})
    existing = store.load()
    if existing is None:
        schedule = build_schedule(load_template(api.TEMPLATE_PATH), profile.to_athlete())
        changes = [f"Welcome {profile.name}! Your plan is fitted to "
                   f"{weeks_until(profile.start_date, profile.race_date, profile.week_start)} weeks."]
    else:
        schedule, changes = existing, rebuild(existing, profile.to_athlete(), today)
    store.save(schedule)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/?saved=1"
    return response


# ---------- calendar ----------

@router.get("/", response_class=HTMLResponse)
def home(request: Request, saved: int = 0, store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    if store.load() is None:
        return RedirectResponse("/setup", status_code=303)
    banner = _banner(["Your setup is saved."]) if saved else None
    return templates.TemplateResponse(request, "calendar.html", _calendar_ctx(store, today, banner=banner))


@router.get("/ui/calendar", response_class=HTMLResponse)
def calendar_partial(request: Request, around: date | None = None, store: SqliteStore = Depends(api.get_store),
                     today: date = Depends(api.get_today)):
    return templates.TemplateResponse(request, "_calendar.html", _calendar_ctx(store, today, around))


@router.get("/ui/day/{day}", response_class=HTMLResponse)
def day_panel(request: Request, day: date, store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    return templates.TemplateResponse(request, "_day_inner.html", {"ctx": _day_ctx(store, day, today)})


def _after_change(request: Request, store: SqliteStore, today: date, day: date | None, around: str | None,
                  changes: list[str], error: bool):
    ctx = _calendar_ctx(store, today, date.fromisoformat(around) if around else None, _banner(changes, error))
    if day is not None:
        ctx["panel"] = _day_ctx(store, day, today)
    return templates.TemplateResponse(request, "_calendar.html", ctx)


@router.post("/ui/day/{day}/action", response_class=HTMLResponse)
async def day_action(request: Request, day: date, store: SqliteStore = Depends(api.get_store),
                     today: date = Depends(api.get_today)):
    form = await request.form()
    schedule = store.load()
    try:
        a = api.ActionIn(
            kind=form.get("kind"),
            workout_id=int(form["workout_id"]) if form.get("workout_id") else None,
            discipline=form.get("discipline") or None,
            new_date=form.get("new_date") or None,
            duration_min=int(form["duration_min"]) if form.get("duration_min") else None,
            intensity=int(form.get("intensity") or 2),
        )
        changes, error = api.perform_action(schedule, day, a, today), False
        store.save(schedule)
    except (actions.ActionError, ValidationError, ValueError) as e:
        changes, error = [str(e) if isinstance(e, actions.ActionError) else "Please fill in the form"], True
    return _after_change(request, store, today, day, form.get("around"), changes, error)


@router.post("/ui/day/{day}/checkin", response_class=HTMLResponse)
async def day_checkin(request: Request, day: date, store: SqliteStore = Depends(api.get_store),
                      today: date = Depends(api.get_today)):
    form = await request.form()
    schedule = store.load()
    outcome = form.get("outcome", "done")
    try:
        c = api.CheckInIn(
            date=day,
            workout_id=int(form["workout_id"]) if form.get("workout_id") else None,
            completed=outcome != "missed",
            actual_duration_min=int(form["minutes"]) if form.get("minutes") and outcome != "missed" else None,
            rpe=int(form["rpe"]) if form.get("rpe") and outcome != "missed" else None,
            fatigue=int(form.get("fatigue") or 3),
            soreness=int(form.get("soreness") or 1),
            notes=form.get("notes", ""),
        )
        api.check_checkin(schedule, c, today)
        changes = apply_checkin(schedule, CheckIn(**c.model_dump()))
        store.save(schedule)
        changes, error = ["Checked in."] + changes, False
    except actions.ActionError as e:
        changes, error = [str(e)], True
    except (ValidationError, ValueError):
        changes, error = ["Please fill in the check-in"], True
    return _after_change(request, store, today, day, form.get("around"), changes, error)


@router.post("/ui/undo", response_class=HTMLResponse)
async def undo(request: Request, store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    form = await request.form()
    schedule = store.load()
    try:
        changes, error = actions.undo(schedule), False
        store.save(schedule)
    except actions.ActionError as e:
        changes, error = [str(e)], True
    return _after_change(request, store, today, None, form.get("around"), changes, error)


@router.get("/finish", response_class=HTMLResponse)
def finish(request: Request, store: SqliteStore = Depends(api.get_store)):
    schedule = store.load()
    if schedule is None:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(request, "finish.html", {"s": summarize(schedule)})
