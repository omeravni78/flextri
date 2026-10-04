"""Command line entry point: onboard, see today, check in, and close out the block."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .adaptation import apply_checkin
from .ceremony import summarize
from .models import Athlete, CheckIn
from .scaling import build_schedule, weeks_until
from .storage import load_schedule, load_template, save_schedule

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _onboard(args: argparse.Namespace) -> None:
    template = load_template(args.template)
    athlete = Athlete(
        name=args.name,
        start_date=date.fromisoformat(args.start),
        race_date=date.fromisoformat(args.race),
        available_days={DAYS.index(d) for d in args.days.split(",")},
        max_session_min=args.max_session,
        week_start=DAYS.index(args.week_start),
    )
    schedule = build_schedule(template, athlete)
    save_schedule(schedule, args.data)
    n = weeks_until(athlete.start_date, athlete.race_date, athlete.week_start)
    print(f"Welcome {athlete.name}! {template.name} ({template.length_weeks} weeks) fitted to {n} weeks, "
          f"{len(schedule.workouts)} sessions until {athlete.race_date}.")


def _today(args: argparse.Namespace) -> None:
    schedule = load_schedule(args.data)
    day = date.fromisoformat(args.date) if args.date else date.today()
    for w in schedule.on(day):
        extra = f"  [{'; '.join(w.adjustments)}]" if w.adjustments else ""
        key = " KEY" if w.workout.key else ""
        print(f"#{w.id} {w.workout.discipline.value} {w.workout.duration_min} min z{w.workout.intensity}"
              f"{key} ({w.status.value}) {w.workout.description}{extra}")


def _checkin(args: argparse.Namespace) -> None:
    schedule = load_schedule(args.data)
    checkin = CheckIn(
        date=date.fromisoformat(args.date) if args.date else date.today(),
        workout_id=args.workout,
        completed=not args.missed,
        actual_duration_min=args.minutes,
        rpe=args.rpe,
        fatigue=args.fatigue,
        soreness=args.soreness,
        sleep_hours=args.sleep,
        notes=args.notes,
    )
    changes = apply_checkin(schedule, checkin)
    save_schedule(schedule, args.data)
    print("Checked in." + ("".join(f"\n- {c}" for c in changes) or " No changes to your plan."))


def _finish(args: argparse.Namespace) -> None:
    print(summarize(load_schedule(args.data)).render())


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="flextri")
    p.add_argument("--data", type=Path, default=Path("flextri_data.json"))
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("onboard")
    o.add_argument("--template", type=Path, required=True)
    o.add_argument("--name", required=True)
    o.add_argument("--start", required=True, help="YYYY-MM-DD")
    o.add_argument("--race", required=True, help="YYYY-MM-DD")
    o.add_argument("--days", default=",".join(DAYS), help="training days, e.g. mon,tue,thu,sat,sun")
    o.add_argument("--max-session", type=int)
    o.add_argument("--week-start", choices=["mon", "sun"], default="mon")
    o.set_defaults(fn=_onboard)

    t = sub.add_parser("today")
    t.add_argument("--date")
    t.set_defaults(fn=_today)

    c = sub.add_parser("checkin")
    c.add_argument("--date")
    c.add_argument("--workout", type=int)
    c.add_argument("--missed", action="store_true")
    c.add_argument("--minutes", type=int)
    c.add_argument("--rpe", type=int)
    c.add_argument("--fatigue", type=int, default=3)
    c.add_argument("--soreness", type=int, default=1)
    c.add_argument("--sleep", type=float)
    c.add_argument("--notes", default="")
    c.set_defaults(fn=_checkin)

    f = sub.add_parser("finish")
    f.set_defaults(fn=_finish)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
