"""Push scheduled flexTri workouts to the Garmin Connect calendar.

Garmin's official Training API is closed to new developers (applications paused
since spring 2026), so this uses the unofficial ``garminconnect`` library, which
logs in as the athlete the way the Garmin Connect mobile app does. Workouts land
in the Garmin Connect calendar and sync to the watch on its next sync.

    pip install garminconnect
    GARMIN_EMAIL=... GARMIN_PASSWORD=... python -m flextri.garmin --days 7

It reads the same SQLite database as the web app (``FLEXTRI_DB``, default
``flextri.db`` in flexTri's data folder, see ``paths.py``); ``--data`` reads a
CLI JSON schedule instead.

After the first login the tokens are cached in the data folder (``GARMINTOKENS``
overrides it) and the password is no longer needed.

Without logging in, ``--export DIR`` writes one Garmin workout JSON file per
session instead. Import those in Garmin Connect web with the "Share your Garmin
Connect workout" Chrome extension, then drag them onto the calendar.
"""

from __future__ import annotations

import argparse
import json
import re
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from .models import Discipline, Schedule, ScheduledWorkout, Workout, WorkoutStatus

NAME_PREFIX = "flexTri: "

_SPORTS = {
    Discipline.RUN: (1, "running"),
    Discipline.BIKE: (2, "cycling"),
    Discipline.SWIM: (3, "swimming"),
}
_STEP_TYPES = {"warmup": 1, "cooldown": 2, "interval": 3}
BRICK_BIKE_SHARE = 2 / 3


class GarminClient(Protocol):
    """The slice of ``garminconnect.Garmin`` this module uses."""

    def upload_workout(self, workout_json: dict[str, Any]) -> dict[str, Any]: ...
    def schedule_workout(self, workout_id: int | str, date_str: str) -> dict[str, Any]: ...
    def get_scheduled_workouts(self, year: int, month: int) -> dict[str, Any]: ...


def _step(order: int, kind: str, minutes: int, zone: int | None) -> dict[str, Any]:
    target: dict[str, Any] = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": _STEP_TYPES[kind], "stepTypeKey": kind, "displayOrder": _STEP_TYPES[kind]},
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
        "endConditionValue": float(minutes * 60),
        "targetType": target,
    }
    if zone is not None:
        step["targetType"] = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
        step["zoneNumber"] = zone
    return step


def _steps(minutes: int, zone: int, hr_target: bool) -> list[dict[str, Any]]:
    """Warm-up and cool-down around a main set in the session's zone; short sessions are one step."""
    main_zone = zone if hr_target else None
    if minutes < 20:
        return [_step(1, "interval", minutes, main_zone)]
    edge = max(5, round(minutes * 0.15))
    return [
        _step(1, "warmup", edge, 1 if hr_target else None),
        _step(2, "interval", minutes - 2 * edge, main_zone),
        _step(3, "cooldown", edge, 1 if hr_target else None),
    ]


def _payload(discipline: Discipline, minutes: int, w: Workout, name: str) -> dict[str, Any]:
    sport_id, sport_key = _SPORTS[discipline]
    sport = {"sportTypeId": sport_id, "sportTypeKey": sport_key, "displayOrder": sport_id}
    # Heart rate zones are meaningless on most wrist-based swim tracking, so swims get no target.
    steps = _steps(minutes, w.intensity, hr_target=discipline != Discipline.SWIM)
    return {
        "workoutName": name,
        "description": f"Zone {w.intensity}" + (" · key session" if w.key else ""),
        "sportType": sport,
        "estimatedDurationInSecs": minutes * 60,
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport, "workoutSteps": steps}],
    }


def to_garmin_workouts(sw: ScheduledWorkout) -> list[dict[str, Any]]:
    """Garmin workout payloads for one scheduled session (bricks become a ride plus a run)."""
    w = sw.workout
    label = w.description or w.discipline.value
    if w.discipline in _SPORTS and w.duration_min > 0:
        return [_payload(w.discipline, w.duration_min, w, NAME_PREFIX + label)]
    if w.discipline == Discipline.BRICK and w.duration_min > 0:
        bike = round(w.duration_min * BRICK_BIKE_SHARE)
        return [
            _payload(Discipline.BIKE, bike, w, f"{NAME_PREFIX}{label} (bike)"),
            _payload(Discipline.RUN, w.duration_min - bike, w, f"{NAME_PREFIX}{label} (run)"),
        ]
    return []  # rest and strength stay in flexTri only


def _already_scheduled(client: GarminClient, start: date, end: date) -> set[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    months = {(start.year, start.month), (end.year, end.month)}
    for year, month in sorted(months):
        for item in client.get_scheduled_workouts(year, month).get("calendarItems", []):
            if item.get("itemType") == "workout":
                seen.add((item.get("date", ""), item.get("title", "")))
    return seen


def _window(schedule: Schedule, start: date, days: int):
    end = start + timedelta(days=days - 1)
    for sw in schedule.workouts:
        if start <= sw.date <= end and sw.status == WorkoutStatus.PLANNED:
            for payload in to_garmin_workouts(sw):
                yield sw.date, payload


def export_schedule(schedule: Schedule, out_dir: Path, start: date, days: int) -> list[Path]:
    """Write each planned workout in the window as a Garmin workout JSON file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for day, payload in _window(schedule, start, days):
        slug = re.sub(r"[^a-z0-9]+", "-", payload["workoutName"].removeprefix(NAME_PREFIX).lower()).strip("-")
        path = out_dir / f"{day.isoformat()}_{slug}.json"
        path.write_text(json.dumps(payload, indent=2))
        paths.append(path)
    return paths


def push_schedule(schedule: Schedule, client: GarminClient, start: date, days: int) -> list[str]:
    """Upload and schedule planned workouts from ``start`` for ``days`` days; skips ones already there."""
    seen = _already_scheduled(client, start, start + timedelta(days=days - 1))
    lines = []
    for day, payload in _window(schedule, start, days):
        key = (day.isoformat(), payload["workoutName"])
        if key in seen:
            lines.append(f"{key[0]} {key[1]}: already on Garmin")
            continue
        created = client.upload_workout(payload)
        client.schedule_workout(created["workoutId"], key[0])
        lines.append(f"{key[0]} {key[1]}: added")
    return lines


def _login() -> GarminClient:
    try:
        from garminconnect import Garmin
    except ImportError:
        raise SystemExit("Install the Garmin client first: pip install garminconnect") from None
    from .paths import garmin_tokens

    tokens = str(garmin_tokens())
    client = Garmin(os.environ.get("GARMIN_EMAIL"), os.environ.get("GARMIN_PASSWORD"),
                    prompt_mfa=lambda: input("Garmin MFA code: "))
    client.login(tokens)
    return client


def _test_schedule(day: date) -> Schedule:
    """One 20-minute easy run, to check the Garmin connection without a flexTri plan."""
    from .models import Athlete, Phase

    run = ScheduledWorkout(id=1, date=day, workout=Workout(Discipline.RUN, 20, 2, "test run"), phase=Phase.BASE)
    return Schedule(athlete=Athlete("test", day, day), plan_name="test", workouts=[run])


def _load(args: argparse.Namespace) -> Schedule:
    from .storage import SqliteStore, load_schedule

    if args.test:
        return _test_schedule(date.fromisoformat(args.start) if args.start else date.today())
    if args.data:
        return load_schedule(args.data)
    if args.db is None:
        from .paths import db_path

        args.db = db_path()
    if not Path(args.db).exists():
        raise SystemExit(f"No flexTri database at {args.db}; finish the setup wizard first or pass --db.")
    schedule = SqliteStore(args.db).load()
    if schedule is None:
        raise SystemExit(f"{args.db} has no plan yet; finish the setup wizard first.")
    return schedule


def main(argv: list[str] | None = None) -> None:

    p = argparse.ArgumentParser(prog="python -m flextri.garmin",
                                description="Send upcoming flexTri workouts to Garmin Connect.")
    p.add_argument("--db", type=Path, help="web app SQLite database (default: the app's own)")
    p.add_argument("--data", type=Path, help="CLI JSON schedule, used instead of --db")
    p.add_argument("--start", help="YYYY-MM-DD, default today")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--test", action="store_true",
                   help="send one 20-minute easy run instead of the plan, to check the connection")
    p.add_argument("--export", type=Path, metavar="DIR",
                   help="write workout JSON files for the Chrome extension instead of logging in")
    args = p.parse_args(argv)
    start = date.fromisoformat(args.start) if args.start else date.today()
    if args.export:
        paths = export_schedule(_load(args), args.export, start, args.days)
        print("\n".join(str(path) for path in paths) or "Nothing to export in that window.")
        return
    lines = push_schedule(_load(args), _login(), start, args.days)
    print("\n".join(lines) or "Nothing to send in that window.")


if __name__ == "__main__":
    main()
