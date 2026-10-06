"""The Connect Garmin page: log in once, send the week to the watch, clean up old workouts, disconnect."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..garmin import push_schedule
from ..garmin_account import GarminAccount, GarminLoginError, library_problem
from ..garmin_cleanup import delete_old, scan
from ..storage import SqliteStore
from . import api

log = logging.getLogger(__name__)

router = APIRouter(prefix="/garmin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

SEND_DAYS = 7
_account = GarminAccount()


def get_account() -> GarminAccount:
    return _account


def _page(request: Request, account: GarminAccount, **ctx) -> HTMLResponse:
    ctx.setdefault("error", None)
    ctx.setdefault("result", None)
    return templates.TemplateResponse(request, "garmin.html", {
        "connected": account.connected,
        "waiting_for_code": account.waiting_for_code,
        "send_days": SEND_DAYS,
        "library_problem": library_problem(),
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
