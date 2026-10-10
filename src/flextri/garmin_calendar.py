"""Read the coming week back from the Garmin Connect calendar, and take sessions off it.

The Garmin page shows "here is what Garmin thinks your week looks like": every workout
scheduled on the Garmin Connect calendar in the window, whoever put it there. The athlete
can remove some or all of them. Removing takes the session off the calendar; for a
workout flexTri made, which exists only for that one date, the workout itself is deleted
too, so it stops taking a workout slot on the watch. Workouts the athlete saved
themselves stay in their Garmin library. Recorded activities are never touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Protocol

from .garmin import NAME_PREFIX

SPORTS = {"running": "run", "cycling": "bike", "swimming": "swim", "strength_training": "strength"}


class GarminCalendar(Protocol):
    def get_scheduled_workouts(self, year: int, month: int) -> dict[str, Any]: ...
    def unschedule_workout(self, scheduled_workout_id: int | str) -> Any: ...
    def delete_workout(self, workout_id: int | str) -> Any: ...


@dataclass(frozen=True)
class GarminSession:
    schedule_id: int  # the calendar entry; one workout can sit on several dates
    workout_id: int | None
    day: date
    title: str
    sport: str  # run, bike, swim, strength or other
    minutes: int | None
    from_flextri: bool


def _months(start: date, end: date) -> list[tuple[int, int]]:
    first, last = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
    return [(i // 12, i % 12 + 1) for i in range(first, last + 1)]


def _minutes(item: dict[str, Any]) -> int | None:
    for key in ("estimatedDurationInSecs", "duration"):
        seconds = item.get(key)
        if isinstance(seconds, (int, float)) and seconds > 0:
            return round(seconds / 60)
    return None


def _session(item: dict[str, Any]) -> GarminSession | None:
    if item.get("itemType") != "workout" or not item.get("id") or not item.get("date"):
        return None
    title = item.get("title") or "Workout"
    return GarminSession(
        schedule_id=int(item["id"]),
        workout_id=int(item["workoutId"]) if item.get("workoutId") else None,
        day=date.fromisoformat(item["date"][:10]),
        title=title.removeprefix(NAME_PREFIX),
        sport=SPORTS.get(item.get("sportTypeKey") or "", "other"),
        minutes=_minutes(item),
        from_flextri=title.startswith(NAME_PREFIX),
    )


def _calendar(client: GarminCalendar, start: date, end: date) -> list[GarminSession]:
    sessions = []
    for year, month in _months(start, end):
        for item in client.get_scheduled_workouts(year, month).get("calendarItems") or []:
            session = _session(item)
            if session is not None:
                sessions.append(session)
    return sessions


def read_week(client: GarminCalendar, start: date, days: int = 7) -> list[GarminSession]:
    """Workouts on the Garmin calendar from ``start`` for ``days`` days, in date order."""
    end = start + timedelta(days=days - 1)
    return sorted((s for s in _calendar(client, start, end) if start <= s.day <= end),
                  key=lambda s: (s.day, s.title))


def by_day(sessions: list[GarminSession], start: date, days: int = 7) -> list[tuple[date, list[GarminSession]]]:
    """Every day of the window with its sessions, empty days included."""
    return [(start + timedelta(days=i), [s for s in sessions if s.day == start + timedelta(days=i)])
            for i in range(days)]


def remove(client: GarminCalendar, start: date, days: int, schedule_ids: Iterable[int]) -> list[GarminSession]:
    """Take the chosen sessions off the Garmin calendar; returns the ones removed.

    Only sessions still on the calendar inside the window are touched, so a stale page
    can't remove anything else.
    """
    wanted = set(schedule_ids)
    end = start + timedelta(days=days - 1)
    # Look a month either side, so a flexTri workout also scheduled outside the window keeps its template.
    everything = _calendar(client, start - timedelta(days=31), end + timedelta(days=31))
    chosen = [s for s in everything if s.schedule_id in wanted and start <= s.day <= end]
    gone = {s.schedule_id for s in chosen}
    deleted: set[int] = set()
    for s in chosen:
        if s.workout_id in deleted:
            continue  # deleting the workout already cleared this entry
        others = [o for o in everything if o.workout_id == s.workout_id and o.schedule_id not in gone]
        if s.from_flextri and s.workout_id and not others:
            client.delete_workout(s.workout_id)  # also clears its calendar entries
            deleted.add(s.workout_id)
        else:
            client.unschedule_workout(s.schedule_id)
    return chosen
