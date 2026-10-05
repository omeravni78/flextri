"""Free workout slots on a Garmin watch by deleting old workouts from Garmin Connect.

Coaching apps such as TrainingPeaks create one Garmin Connect workout per session
and never remove it, so the watch eventually reports that workout storage is full.
The watch mirrors the Garmin Connect workout library on each sync, so deleting
workouts there frees space on the watch after its next sync.

    python -m flextri.garmin_cleanup              # report only, changes nothing
    python -m flextri.garmin_cleanup --delete     # delete after you confirm

Only workouts whose every calendar date is before ``--before`` (default today)
are candidates. Workouts that are scheduled today or later, or that were never
put on the calendar (ones you saved yourself), are kept. Deleting a workout does
not touch recorded activities.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


class GarminLibrary(Protocol):
    def get_workouts(self, start: int = 0, limit: int = 100) -> list[dict[str, Any]]: ...
    def get_scheduled_workouts(self, year: int, month: int) -> dict[str, Any]: ...
    def delete_workout(self, workout_id: int | str) -> Any: ...


@dataclass
class Report:
    total: int
    old: list[dict[str, Any]]  # library workouts only scheduled before the cutoff
    upcoming: int
    unscheduled: int


def _library(client: GarminLibrary) -> list[dict[str, Any]]:
    workouts, start = [], 0
    while True:
        page = client.get_workouts(start, 100) or []
        workouts += page
        if len(page) < 100:
            return workouts
        start += 100


def _months(around: date, back: int, ahead: int) -> list[tuple[int, int]]:
    index = around.year * 12 + around.month - 1
    return [(i // 12, i % 12 + 1) for i in range(index - back, index + ahead + 1)]


def scan(client: GarminLibrary, before: date, months_back: int = 18, months_ahead: int = 12) -> Report:
    dates: dict[int, list[str]] = defaultdict(list)
    for year, month in _months(before, months_back, months_ahead):
        for item in client.get_scheduled_workouts(year, month).get("calendarItems", []):
            if item.get("itemType") == "workout" and item.get("workoutId"):
                dates[int(item["workoutId"])].append(item.get("date", ""))
    library = _library(client)
    cutoff = before.isoformat()
    old = [w for w in library if dates.get(int(w["workoutId"])) and max(dates[int(w["workoutId"])]) < cutoff]
    upcoming = sum(1 for w in library if dates.get(int(w["workoutId"])) and max(dates[int(w["workoutId"])]) >= cutoff)
    return Report(total=len(library), old=old, upcoming=upcoming, unscheduled=len(library) - len(old) - upcoming)


def delete_old(client: GarminLibrary, report: Report) -> int:
    for w in report.old:
        client.delete_workout(w["workoutId"])
    return len(report.old)


def main(argv: list[str] | None = None) -> None:
    from .garmin import _login

    p = argparse.ArgumentParser(prog="python -m flextri.garmin_cleanup",
                                description="Delete old workouts from Garmin Connect to free space on the watch.")
    p.add_argument("--before", help="YYYY-MM-DD, default today")
    p.add_argument("--delete", action="store_true", help="delete the old workouts (asks first)")
    p.add_argument("--yes", action="store_true", help="skip the confirmation question")
    args = p.parse_args(argv)
    before = date.fromisoformat(args.before) if args.before else date.today()

    client = _login()
    report = scan(client, before)
    print(f"Garmin Connect workout library: {report.total} workouts")
    print(f"  {len(report.old)} only scheduled before {before} (can be deleted)")
    print(f"  {report.upcoming} scheduled {before} or later (kept)")
    print(f"  {report.unscheduled} never on the calendar (kept)")
    for w in report.old[:10]:
        print(f"    e.g. {w.get('workoutName', w['workoutId'])}")
    if not args.delete or not report.old:
        if report.old:
            print("Nothing deleted. Run again with --delete to remove them.")
        return
    if not args.yes and input(f"Delete {len(report.old)} workouts from Garmin Connect? This can't be undone. [y/N] ").strip().lower() != "y":
        print("Nothing deleted.")
        return
    print(f"Deleted {delete_old(client, report)} workouts. Sync your watch to free the space.")


if __name__ == "__main__":
    main()
