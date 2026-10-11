"""Send a week to Garmin without leaving the screen: the calendar and all three Today looks post here."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..garmin import push_schedule
from ..garmin_account import GarminAccount, GarminLoginError
from ..storage import SqliteStore
from . import api
from .garmin_ui import SEND_DAYS, _pretty, get_account

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/garmin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

MAX_DAYS = 14


def _note(request: Request, title: str, *, error: bool = False, connect: bool = False,
          lines: list[str] | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "_garmin_sent.html", {
        "title": title, "error": error, "connect": connect, "lines": lines or []})


def window(today: date, start: date | None, days: int) -> tuple[date, int] | None:
    """The days to send: from ``start`` (never before today) to ``start + days - 1``; None when it is all past."""
    first = start or today
    last = first + timedelta(days=min(max(days, 1), MAX_DAYS) - 1)
    first = max(first, today)
    return None if last < first else (first, (last - first).days + 1)


@router.post("/send", response_class=HTMLResponse)
def send_week(request: Request, start: str = Form(""), days: int = Form(SEND_DAYS),
              account: GarminAccount = Depends(get_account), store: SqliteStore = Depends(api.get_store),
              today: date = Depends(api.get_today)):
    """Upload one week of planned sessions and answer with a short note for the screen that asked."""
    schedule = store.load()
    if schedule is None:
        return _note(request, "Finish the setup first, then send your week.", error=True)
    try:
        span = window(today, date.fromisoformat(start) if start else None, days)
    except ValueError:
        return _note(request, "That week doesn't look like a date flexTri knows.", error=True)
    if span is None:
        return _note(request, "That week is over, so there is nothing to send.")
    if not account.connected:
        return _note(request, "Connect Garmin once, then send your week from here.", connect=True)
    first, count = span
    try:
        lines = push_schedule(schedule, account.client(), first, count)
    except GarminLoginError as e:
        return _note(request, str(e), error=True, connect=True)
    except Exception as e:
        log.exception("Garmin request failed")
        return _note(request, f"Garmin Connect refused the upload: {e}", error=True)
    added = sum(line.endswith(": added") for line in lines)
    title = (f"Sent {added} workout{'s' * (added != 1)}. Sync your watch to get them." if added
             else "Already on Garmin, nothing new to send." if lines else "No workouts to send that week.")
    return _note(request, title, lines=[_pretty(line) for line in lines])
