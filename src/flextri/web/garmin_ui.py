"""The Connect Garmin page: log in once, send the week to the watch, see and edit what Garmin has scheduled,
clean up old workouts, disconnect. Drawn in the athlete's home screen look."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from .. import today_view
from ..garmin import push_schedule
from ..garmin_calendar import by_day, read_week, remove
from ..garmin_account import GarminAccount, GarminLoginError, library_problem
from ..scaling import week_first_day, weeks_until
from ..garmin_cleanup import delete_old, scan
from ..storage import SqliteStore
from . import api
from .ui import templates

log = logging.getLogger(__name__)


def _remember_look(request: Request, store: SqliteStore = Depends(api.get_store)) -> None:
    schedule = store.load()
    look = schedule.athlete.look if schedule is not None else today_view.DEFAULT_LOOK
    request.state.look = look if look in today_view.LOOKS else today_view.DEFAULT_LOOK


router = APIRouter(prefix="/garmin", dependencies=[Depends(_remember_look)])

SEND_DAYS = 7
_account = GarminAccount()


def get_account() -> GarminAccount:
    return _account


def _page(request: Request, account: GarminAccount, **ctx) -> HTMLResponse:
    ctx.setdefault("error", None)
    ctx.setdefault("result", None)
    return templates.TemplateResponse(request, "garmin.html", {
        "connected": account.connected,
        "protection": account.protection() if account.connected else None,
        "waiting_for_code": account.waiting_for_code,
        "send_days": SEND_DAYS,
        "library_problem": library_problem(),
        "look": request.state.look,
        **ctx,
    })


@router.get("", response_class=HTMLResponse)
def garmin_page(request: Request, account: GarminAccount = Depends(get_account)):
    return _page(request, account)


@router.post("/connect", response_class=HTMLResponse)
def connect(request: Request, email: str = Form(""), password: str = Form(""),
            account: GarminAccount = Depends(get_account)):
    try:
        done = account.connect(email, password)
    except GarminLoginError as e:
        return _page(request, account, error=str(e), email=email)
    return _page(request, account, result={"title": "Garmin connected"} if done else None)


@router.post("/code", response_class=HTMLResponse)
def code(request: Request, code: str = Form(""), account: GarminAccount = Depends(get_account)):
    try:
        account.submit_code(code)
    except GarminLoginError as e:
        return _page(request, account, error=str(e))
    return _page(request, account, result={"title": "Garmin connected"})


@router.post("/cancel", response_class=HTMLResponse)
def cancel(request: Request, account: GarminAccount = Depends(get_account)):
    account.cancel()
    return _page(request, account)


@router.post("/send", response_class=HTMLResponse)
def send(request: Request, account: GarminAccount = Depends(get_account),
         store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    schedule = store.load()
    if schedule is None:
        return _page(request, account, error="Finish the setup first, then send your week.")
    try:
        lines = push_schedule(schedule, account.client(), today, SEND_DAYS)
    except GarminLoginError as e:
        return _page(request, account, error=str(e))
    except Exception as e:
        log.exception("Garmin request failed")
        return _page(request, account, error=f"Garmin Connect refused the upload: {e}")
    added = sum(line.endswith(": added") for line in lines)
    title = (f"Sent {added} workout{'s' * (added != 1)}. Sync your watch to get them."
             if added else "Nothing new to send." if lines else f"No workouts in the next {SEND_DAYS} days.")
    return _page(request, account, result={"title": title, "lines": [_pretty(line) for line in lines]})


def _pretty(line: str) -> str:
    day, _, rest = line.partition(" ")
    return f"{date.fromisoformat(day):%a %d %b} · {rest.removeprefix('flexTri: ')}"


@router.post("/cleanup", response_class=HTMLResponse)
def cleanup(request: Request, account: GarminAccount = Depends(get_account), today: date = Depends(api.get_today)):
    """Step one: count old workouts, delete nothing yet."""
    try:
        report = scan(account.client(), today)
    except GarminLoginError as e:
        return _page(request, account, error=str(e))
    except Exception as e:
        log.exception("Garmin request failed")
        return _page(request, account, error=f"Couldn't read your Garmin workouts: {e}")
    return _page(request, account, cleanup={
        "old": len(report.old), "upcoming": report.upcoming, "unscheduled": report.unscheduled,
        "examples": [w.get("workoutName", "") for w in report.old[:5]],
    })


@router.post("/cleanup/confirm", response_class=HTMLResponse)
def cleanup_confirm(request: Request, account: GarminAccount = Depends(get_account),
                    today: date = Depends(api.get_today)):
    try:
        client = account.client()
        deleted = delete_old(client, scan(client, today))
    except GarminLoginError as e:
        return _page(request, account, error=str(e))
    except Exception as e:
        log.exception("Garmin request failed")
        return _page(request, account, error=f"Garmin Connect stopped the clean-up: {e}")
    return _page(request, account, result={
        "title": f"Deleted {deleted} old workout{'s' * (deleted != 1)}. Sync your watch to free the space."})


@router.post("/disconnect", response_class=HTMLResponse)
def disconnect(request: Request, account: GarminAccount = Depends(get_account)):
    account.disconnect()
    return _page(request, account, result={"title": "Garmin disconnected. flexTri deleted its Garmin login."})


# ---------- the week as Garmin sees it (loaded into the page with HTMX) ----------
# Same weeks as the calendar: seven days from the athlete's chosen first weekday, browsed with ‹ ›.

def _span(store: SqliteStore, today: date, around: date | None) -> dict:
    """The calendar week holding ``around`` (default today), labelled like the calendar labels it."""
    schedule = store.load()
    a = schedule.athlete if schedule is not None else None
    ws = a.week_start if a else 0
    first = week_first_day(around or today, ws)
    number = total = None
    if a:
        total = weeks_until(a.start_date, a.race_date, ws)
        block_first = week_first_day(a.race_date, ws) - timedelta(weeks=total - 1)
        n = (first - block_first).days // 7 + 1
        number = n if 1 <= n <= total else None
    current = first <= today < first + timedelta(days=7)
    label = "this week" if current else f"in week {number}" if number else f"in the week of {first.day} {first:%b}"
    return {"first": first, "last": first + timedelta(days=6), "number": number, "total": total, "current": current, "label": label,
            "prev": first - timedelta(weeks=1), "next": first + timedelta(weeks=1)}


def _around(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _week(request: Request, account: GarminAccount, store: SqliteStore, today: date,
          around: date | None = None, **ctx) -> HTMLResponse:
    ctx.setdefault("error", None)
    ctx.setdefault("result", None)
    ctx.setdefault("confirm", None)
    span = _span(store, today, around)
    first = span["first"]
    days, sessions = None, []
    if account.connected:
        try:
            sessions = read_week(account.client(), first, 7)
            days = by_day(sessions, first, 7)
            if ctx["confirm"]:
                ids = set(ctx["confirm"]["ids"])
                picked = [s for s in sessions if ctx["confirm"]["all"] or s.schedule_id in ids]
                ctx["confirm"] = {"sessions": picked, "all": ctx["confirm"]["all"]} if picked else None
                if not picked:
                    ctx["error"] = "Those sessions are no longer on Garmin."
        except GarminLoginError as e:
            ctx["error"] = str(e)
        except Exception as e:
            log.exception("Garmin request failed")
            ctx["error"] = f"Couldn't read your Garmin calendar: {e}"
    return templates.TemplateResponse(request, "_garmin_week.html", {
        "connected": account.connected, "days": days, "sessions": sessions, "today": today, "span": span,
        "look": request.state.look, **ctx,
    })


@router.get("/week", response_class=HTMLResponse)
def week(request: Request, around: str = "", account: GarminAccount = Depends(get_account),
         store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    return _week(request, account, store, today, _around(around))


def _ids(form) -> list[int]:
    return [int(v) for v in form.getlist("ids") if str(v).isdigit()]


@router.post("/week/delete", response_class=HTMLResponse)
async def week_delete(request: Request, account: GarminAccount = Depends(get_account),
                      store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    """Step one: show which sessions would go, delete nothing yet."""
    form = await request.form()
    around = _around(form.get("around"))
    every = form.get("all") == "1"
    ids = _ids(form)
    if not ids and not every:
        return _week(request, account, store, today, around, error="Tick the sessions to delete first, or use Delete all.")
    return _week(request, account, store, today, around, confirm={"ids": ids, "all": every})


@router.post("/week/delete/confirm", response_class=HTMLResponse)
async def week_delete_confirm(request: Request, account: GarminAccount = Depends(get_account),
                              store: SqliteStore = Depends(api.get_store), today: date = Depends(api.get_today)):
    form = await request.form()
    around = _around(form.get("around"))
    ids = _ids(form)
    try:
        removed = remove(account.client(), _span(store, today, around)["first"], 7, ids)
    except GarminLoginError as e:
        return _week(request, account, store, today, around, error=str(e))
    except Exception as e:
        log.exception("Garmin request failed")
        return _week(request, account, store, today, around, error=f"Garmin Connect stopped the delete: {e}")
    n = len(removed)
    title = (f"Deleted {n} session{'s' * (n != 1)} from Garmin. Sync your watch to update it."
             if n else "Those sessions were already gone from Garmin.")
    return _week(request, account, store, today, around, result={"title": title})
