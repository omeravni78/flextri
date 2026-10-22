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

from . import steps
from .models import Discipline, Schedule, ScheduledWorkout, Workout, WorkoutStatus

# Garmin keeps only the first 32 characters of a workout name, so names start with
# the sport ("RUN 8x30s hill strides") and carry no flexTri marker. flexTri knows its
# own workouts by the ids it saved when sending them (SENT_FILE). Workouts sent
# before that were named "flexTri: ..." and are still recognised by NAME_PREFIX.
NAME_LIMIT = 32
NAME_PREFIX = "flexTri: "
SENT_FILE = "garmin_sent.json"

# Garmin's workout sport ids (garminconnect.workout.SportType): id 3 is "other",
# which showed swims with a generic icon. displayOrder follows Garmin's own payloads.
_SPORTS = {
    Discipline.RUN: (1, "running", 1),
    Discipline.BIKE: (2, "cycling", 2),
    Discipline.SWIM: (4, "swimming", 3),
}
_SPORT_WORDS = {Discipline.RUN: "RUN", Discipline.BIKE: "BIKE", Discipline.SWIM: "SWIM"}
# Garmin asks swim workouts for a pool length; flexTri plans count swims in meters.
_POOL = {"poolLength": 25.0, "poolLengthUnit": {"unitId": 1, "unitKey": "meter", "factor": 100.0}}
_STEP_TYPES = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4, "rest": 5}
BRICK_BIKE_SHARE = 2 / 3


class GarminClient(Protocol):
    """The slice of ``garminconnect.Garmin`` this module uses."""

    def upload_workout(self, workout_json: dict[str, Any]) -> dict[str, Any]: ...
    def schedule_workout(self, workout_id: int | str, date_str: str) -> dict[str, Any]: ...
    def get_scheduled_workouts(self, year: int, month: int) -> dict[str, Any]: ...


def workout_name(discipline: Discipline, label: str) -> str:
    """Sport first, cut to what Garmin keeps, e.g. "RUN easy with 8x30s hill strides"."""
    name = f"{_SPORT_WORDS[discipline]} {label}"
    if len(name) > NAME_LIMIT:
        name = name[:NAME_LIMIT + 1].rsplit(" ", 1)[0]  # don't end on half a word
    return name.rstrip(" ,:;(+-")


def is_flextri(title: str, workout_id: int | None = None, sent: set[int] | frozenset[int] = frozenset()) -> bool:
    return workout_id in sent or title.startswith(NAME_PREFIX)


def short_title(title: str) -> str:
    """A Garmin workout title without the old "flexTri: " marker."""
    return title.removeprefix(NAME_PREFIX)


def _sent_path() -> Path:
    from .paths import data_dir

    return data_dir() / SENT_FILE


def sent_ids() -> set[int]:
    """Ids of the Garmin workouts flexTri created."""
    try:
        return {int(i) for i in json.loads(_sent_path().read_text())}
    except (OSError, ValueError, TypeError):
        return set()


def save_sent_ids(ids: set[int]) -> None:
    _sent_path().write_text(json.dumps(sorted(ids)))


def _brick_part(label: str, sport: str) -> str:
    """"bike 40 min (12x15s ...)" from "bike 40 min (12x15s ...) + run 20 min easy"."""
    for part in label.split(" + "):
        if part.lower().startswith(sport + " "):
            return "brick " + part[len(sport) + 1:]
    return label if "brick" in label.lower() else f"brick {label}"


_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_HR_ZONE = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
_END = {  # Garmin's end conditions (garminconnect.workout.ConditionType)
    "lap": {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True},
    "time": {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
    "distance": {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True},
    "fixed.rest": {"conditionTypeId": 8, "conditionTypeKey": "fixed.rest", "displayOrder": 8, "displayable": True},
}


def _step(order: int, kind: str, end: str, value: float | None, zone: int | None, note: str = "") -> dict[str, Any]:
    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": _STEP_TYPES[kind], "stepTypeKey": kind, "displayOrder": _STEP_TYPES[kind]},
        "endCondition": _END[end],
        "endConditionValue": value,
        "targetType": _HR_ZONE if zone is not None else _NO_TARGET,
    }
    if end == "distance":
        step["preferredEndConditionUnit"] = {"unitKey": "meter"}
    if zone is not None:
        step["zoneNumber"] = zone
    if note:
        step["description"] = note
    return step


def _plain_steps(minutes: int, zone: int, hr_target: bool) -> list[dict[str, Any]]:
    """Warm-up and cool-down around a main set in the session's zone; short sessions are one step.

    Used when the plan gives the session no steps of its own.
    """
    main_zone = zone if hr_target else None
    if minutes < 20:
        return [_step(1, "interval", "time", minutes * 60.0, main_zone)]
    edge = max(5, round(minutes * 0.15))
    return [
        _step(1, "warmup", "time", edge * 60.0, 1 if hr_target else None),
        _step(2, "interval", "time", (minutes - 2 * edge) * 60.0, main_zone),
        _step(3, "cooldown", "time", edge * 60.0, 1 if hr_target else None),
    ]


def _plan_steps(plan: steps.Steps, fill_seconds: int, swim: bool) -> list[dict[str, Any]]:
    """The plan's steps as Garmin steps; ``fill_seconds`` is the time the '*' step gets."""
    order, group = 0, 0

    def build(items: steps.Steps, child: int | None) -> list[dict[str, Any]]:
        nonlocal order, group
        out = []
        for s in items:
            order += 1
            if isinstance(s, steps.Repeat):
                group += 1
                me, my_order = group, order
                out.append({
                    "type": "RepeatGroupDTO", "stepOrder": my_order,
                    "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                    "childStepId": me, "numberOfIterations": s.times, "smartRepeat": False,
                    "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7,
                                     "displayable": False},
                    "endConditionValue": float(s.times), "workoutSteps": build(s.steps, me),
                })
                continue
            if s.lap:
                end, value = "lap", None
            elif s.meters:
                end, value = "distance", float(s.meters)
            elif s.kind == "rest" and swim:
                end, value = "fixed.rest", float(s.seconds or 0)
            else:
                end, value = "time", float(fill_seconds if s.fill else s.seconds or 0)
            # Heart rate zones mean little on most wrist-based swim tracking, so swims get no target.
            step = _step(order, s.kind, end, value, None if swim else s.zone, s.note)
            if child is not None:
                step["childStepId"] = child
            out.append(step)
        return out

    return build(plan, None)


def _fit(plan: steps.Steps, seconds: int) -> tuple[int, int] | None:
    """(time for the '*' step, session seconds), or None if the fixed steps don't fit in ``seconds``."""
    fixed = steps.fixed_seconds(plan)
    if not steps.has_fill(plan):
        # As written. Distance and lap steps have no set time, so then the session keeps its minutes.
        open_ended = any(s.meters or s.lap for s in steps.walk(plan))
        return 0, seconds if open_ended or not fixed else fixed
    fill = seconds - fixed
    return (fill, seconds) if fill >= 60 else None


def _payload(discipline: Discipline, minutes: int, w: Workout, name: str,
             plan: steps.Steps | None = None) -> dict[str, Any]:
    sport_id, sport_key, order = _SPORTS[discipline]
    sport = {"sportTypeId": sport_id, "sportTypeKey": sport_key, "displayOrder": order}
    swim = discipline == Discipline.SWIM
    fit = _fit(plan, minutes * 60) if plan else None
    if fit:
        workout_steps, seconds = _plan_steps(plan, fit[0], swim), fit[1]
    else:
        workout_steps, seconds = _plain_steps(minutes, w.intensity, hr_target=not swim), minutes * 60
    payload = {
        "workoutName": name,
        # The full plan text, since the name is cut at 32 characters.
        "description": (f"{w.description} · " if w.description else "") + f"Zone {w.intensity}"
                       + (" · key session" if w.key else ""),
        "sportType": sport,
        "estimatedDurationInSecs": seconds,
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport, "workoutSteps": workout_steps}],
    }
    if swim:
        payload |= _POOL
    return payload


def _parse_or_none(text: str | None, parse) -> Any:
    try:
        return parse(text) if text else None
    except ValueError:
        return None  # a bad steps cell shouldn't stop the upload; `bank check` reports it


def to_garmin_workouts(sw: ScheduledWorkout) -> list[dict[str, Any]]:
    """Garmin workout payloads for one scheduled session (bricks become a ride plus a run).

    When the plan spells out the session's steps (the ``steps`` column, see steps.py), the
    watch gets those; otherwise warm-up, one main block and cool-down.
    """
    from .bank import steps_for

    w = sw.workout
    label = w.description or w.discipline.value
    text = steps_for(w.code, w.description, w.intensity)
    if w.discipline in _SPORTS and w.duration_min > 0:
        plan = _parse_or_none(text, steps.parse)
        return [_payload(w.discipline, w.duration_min, w, workout_name(w.discipline, label), plan)]
    if w.discipline == Discipline.BRICK and w.duration_min > 0:
        legs = _parse_or_none(text, steps.legs) or {}
        bike = round(w.duration_min * BRICK_BIKE_SHARE)
        minutes = {"bike": bike, "run": w.duration_min - bike}
        for sport, leg in legs.items():
            if sport in minutes and not steps.has_fill(leg) and steps.fixed_seconds(leg):
                minutes[sport] = round(steps.fixed_seconds(leg) / 60)
        return [
            _payload(Discipline.BIKE, minutes["bike"], w, workout_name(Discipline.BIKE, _brick_part(label, "bike")),
                     legs.get("bike")),
            _payload(Discipline.RUN, minutes["run"], w, workout_name(Discipline.RUN, _brick_part(label, "run")),
                     legs.get("run")),
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
        slug = re.sub(r"[^a-z0-9]+", "-", short_title(payload["workoutName"]).lower()).strip("-")
        path = out_dir / f"{day.isoformat()}_{slug}.json"
        path.write_text(json.dumps(payload, indent=2))
        paths.append(path)
    return paths


def push_schedule(schedule: Schedule, client: GarminClient, start: date, days: int) -> list[str]:
    """Upload and schedule planned workouts from ``start`` for ``days`` days; skips ones already there."""
    seen = _already_scheduled(client, start, start + timedelta(days=days - 1))
    sent = sent_ids()
    lines = []
    for day, payload in _window(schedule, start, days):
        key = (day.isoformat(), payload["workoutName"])
        if key in seen:
            lines.append(f"{key[0]} {key[1]}: already on Garmin")
            continue
        created = client.upload_workout(payload)
        sent.add(int(created["workoutId"]))
        save_sent_ids(sent)  # after each upload, so a failure halfway still remembers the earlier ones
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
