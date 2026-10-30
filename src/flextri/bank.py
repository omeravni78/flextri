"""The workout bank: every plan as a CSV file, every workout in it with a code saying where it came from.

Plan code:    <race>_<plan weeks>_<source>       e.g. O_8_TRI (Olympic, 8 weeks, Triathlete.com)
Workout code: <plan code>_W<week>_<discipline><n> e.g. O_8_TRI_W2_S1 (first swim of week 2)

A source that publishes a second version of a plan gets a number on its source tag (O_8_TRI2).

The plans folder holds ``plans.csv`` (one row per plan: code, name, race, weeks, source, notes) and one
``<code>.csv`` per plan with a row per workout (see PLAN_COLUMNS). ``day`` is empty in day-free plans and
0 (Mon) .. 6 (Sun) in plans with fixed days. Workout codes are filled in once by ``python -m flextri.bank
code`` and never renumbered: a new row gets the next free number, so a code keeps pointing at the same
workout. The code is only an ID; search the bank by its fields (race, weeks_to_race, discipline, ...).

    python -m flextri.bank code PLANS/O_8_TRI.csv   # fill in missing workout codes
    python -m flextri.bank check                    # validate every plan in the bank
    python -m flextri.bank list [--discipline swim] [--weeks-to-race 6] [--csv bank.csv]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from pathlib import Path

from . import paths, steps
from .models import Discipline, Distance

INDEX = "plans.csv"
INDEX_COLUMNS = ["code", "name", "race", "weeks", "source", "notes"]
PLAN_COLUMNS = ["code", "week", "phase", "day", "slot", "discipline", "duration_min", "intensity", "key", "description", "steps"]
RACE_LETTERS = {Distance.SPRINT: "S", Distance.OLYMPIC: "O", Distance.HALF: "H", Distance.FULL: "I"}
DISCIPLINE_LETTERS = {
    Discipline.SWIM: "S", Discipline.BIKE: "B", Discipline.RUN: "R",
    Discipline.STRENGTH: "G", Discipline.BRICK: "X", Discipline.REST: "Z",
}
PLAN_CODE = re.compile(r"^[SOHI]_\d+_[A-Z][A-Z0-9]*$")


@dataclass
class BankWorkout:
    code: str
    plan_code: str
    plan_name: str
    source: str
    race: str
    plan_weeks: int
    week: int
    weeks_to_race: int  # 0 = race week
    phase: str
    discipline: str
    slot: str | None
    duration_min: int
    intensity: int
    key: bool
    description: str


def plan_code(race: Distance, weeks: int, source: str) -> str:
    return f"{RACE_LETTERS[race]}_{weeks}_{source.upper()}"


def plans_dir() -> Path:
    return Path(paths.bundled("plans"))


def plan_files(directory: Path | None = None) -> list[Path]:
    """The plan CSVs in a folder (everything but the index)."""
    directory = Path(directory or plans_dir())
    return sorted(p for p in directory.glob("*.csv") if p.name != INDEX) if directory.is_dir() else []


def read_index(directory: Path) -> dict[str, dict]:
    path = Path(directory) / INDEX
    if not path.is_file():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {row["code"]: row for row in csv.DictReader(f)}


def read_plan(path: Path) -> dict:
    """A plan CSV (plus its row in plans.csv) as a plan dict: name, code, race, source, notes, weeks."""
    path = Path(path)
    info = read_index(path.parent).get(path.stem)
    if info is None:
        raise ValueError(f"{path.name}: no row for {path.stem} in {INDEX}")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    n = int(info["weeks"])
    weeks = [{"phase": None, "sessions": [], "days": {}} for _ in range(n)]
    for i, r in enumerate(rows, start=2):
        if not 1 <= int(r["week"]) <= n:
            raise ValueError(f"{path.name} line {i}: week {r['week']} is outside 1..{n}")
        week = weeks[int(r["week"]) - 1]
        if week["phase"] not in (None, r["phase"]):
            raise ValueError(f"{path.name} line {i}: week {r['week']} has phases {week['phase']} and {r['phase']}")
        week["phase"] = r["phase"]
        session = {
            "discipline": r["discipline"], "duration_min": int(r["duration_min"]),
            "intensity": int(r["intensity"] or 2), "description": r["description"],
            "key": r["key"].strip().lower() in ("1", "true", "yes", "y"),
            "slot": r["slot"] or None, "code": r["code"] or None,
        }
        if (r.get("steps") or "").strip():
            session["steps"] = r["steps"].strip()
        if r["day"].strip():
            week["days"].setdefault(str(int(r["day"])), []).append(session)
        else:
            week["sessions"].append(session)
    if empty := [str(i) for i, w in enumerate(weeks, start=1) if w["phase"] is None]:
        raise ValueError(f"{path.name}: no workouts in week(s) {', '.join(empty)}")
    return {"name": info["name"], "code": info["code"], "race": info["race"], "source": info["source"],
            "notes": info["notes"], "weeks": weeks}


def write_plan(plan: dict, path: Path) -> None:
    """Write a plan's workouts to its CSV (the plans.csv row is kept by hand)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS)
        writer.writeheader()
        for i, week in enumerate(plan["weeks"], start=1):
            for day, s in _week_sessions(week):
                writer.writerow({
                    "code": s.get("code") or "", "week": i, "phase": week["phase"], "day": day,
                    "slot": s.get("slot") or "", "discipline": s["discipline"], "duration_min": s["duration_min"],
                    "intensity": s.get("intensity", 2), "key": "yes" if s.get("key") else "",
                    "description": s.get("description", ""), "steps": s.get("steps", ""),
                })


def _week_sessions(week: dict) -> list[tuple[str, dict]]:
    """A week's sessions in file order as (day, session): fixed days first (by day), then day-free ones."""
    days = week.get("days", {})
    return [(d, s) for d in sorted(days, key=int) for s in days[d]] + [("", s) for s in week.get("sessions", [])]


def assign_codes(plan: dict) -> int:
    """Give every session without a code its code, in place. Returns how many were added.

    Existing codes are kept as they are; a new session takes the next free number for its
    discipline in that week, so nothing already in the bank is renumbered.
    """
    added = 0
    for i, week in enumerate(plan["weeks"], start=1):
        sessions = [s for _, s in _week_sessions(week)]
        prefix = f"{plan['code']}_W{i}_"
        taken = Counter()
        for s in sessions:
            if (s.get("code") or "").startswith(prefix):
                m = re.fullmatch(r"([A-Z])(\d+)", s["code"][len(prefix):])
                if m:
                    taken[m[1]] = max(taken[m[1]], int(m[2]))
        for s in sessions:
            if not s.get("code"):
                letter = DISCIPLINE_LETTERS[Discipline(s["discipline"])]
                taken[letter] += 1
                s["code"] = f"{prefix}{letter}{taken[letter]}"
                added += 1
    return added


def check_plan(plan: dict) -> list[str]:
    """Problems with a plan's codes; an empty list means it is ready for the bank."""
    code = plan["code"]
    problems = []
    if not PLAN_CODE.match(code):
        problems.append(f"plan code {code} is not <race>_<weeks>_<source>")
    if plan.get("race") not in {d.value for d in Distance}:
        problems.append(f"plan race {plan.get('race')!r} is not one of {[d.value for d in Distance]}")
    elif not code.startswith(plan_code(Distance(plan["race"]), len(plan["weeks"]), "")):
        problems.append(f"plan code {code} does not match race {plan['race']} and {len(plan['weeks'])} weeks")
    seen = set()
    for i, week in enumerate(plan["weeks"], start=1):
        for _, s in _week_sessions(week):
            c = s.get("code")
            letter = DISCIPLINE_LETTERS[Discipline(s["discipline"])]
            if not c:
                problems.append(f"week {i}: {s['discipline']} '{s.get('description', '')}' has no code")
            elif not re.fullmatch(rf"{re.escape(code)}_W{i}_{letter}\d+", c):
                problems.append(f"week {i}: {c} does not fit {code}_W{i}_{letter}<n>")
            elif c in seen:
                problems.append(f"{c} is used twice")
            if s.get("steps"):
                try:
                    steps.check(s["steps"], s["discipline"])
                except ValueError as e:
                    problems.append(f"week {i}: {c or s['discipline']} steps: {e}")
            seen.add(c)
    return problems


@lru_cache(maxsize=1)
def _steps_index() -> dict[str, tuple[str, int, str]]:
    index = {}
    for path in plan_files():
        for week in read_plan(path)["weeks"]:
            for _, s in _week_sessions(week):
                if s.get("code") and s.get("steps"):
                    index[s["code"]] = (s.get("description", ""), s.get("intensity", 2), s["steps"])
    return index


def steps_for(code: str | None, description: str, intensity: int) -> str | None:
    """The watch steps the plan gives this workout, or None.

    Only while the workout is still the plan's: once flexTri has eased it (lower zone) or
    swapped it, the plan's intervals no longer fit, so the caller falls back to plain steps.
    """
    found = _steps_index().get(code or "")
    if found and found[0] == description and found[1] == intensity:
        return found[2]
    return None


def bank_from_plan(plan: dict) -> list[BankWorkout]:
    n = len(plan["weeks"])
    return [
        BankWorkout(
            code=s["code"], plan_code=plan["code"], plan_name=plan["name"], source=plan.get("source", ""),
            race=plan["race"], plan_weeks=n, week=i, weeks_to_race=n - i, phase=week["phase"],
            discipline=s["discipline"], slot=s.get("slot"), duration_min=s["duration_min"],
            intensity=s.get("intensity", 2), key=s.get("key", False), description=s.get("description", ""),
        )
        for i, week in enumerate(plan["weeks"], start=1)
        for _, s in _week_sessions(week)
    ]


def load_bank(directory: Path | None = None) -> list[BankWorkout]:
    """Every workout from every plan in the folder. Raises if a plan's codes are missing or wrong."""
    bank = []
    for path in plan_files(directory):
        plan = read_plan(path)
        if problems := check_plan(plan):
            raise ValueError(f"{path.name}: " + "; ".join(problems))
        bank.extend(bank_from_plan(plan))
    return bank


def search(bank: list[BankWorkout], **filters) -> list[BankWorkout]:
    """Workouts whose fields equal every given filter, e.g. search(bank, discipline="swim", weeks_to_race=6)."""
    return [w for w in bank if all(getattr(w, k) == v for k, v in filters.items() if v is not None)]


def _code(args: argparse.Namespace) -> int:
    path = Path(args.plan)
    plan = read_plan(path)
    added = assign_codes(plan)
    write_plan(plan, path)
    print(f"{path.name}: {added} workout code(s) added")
    return 0


def _check(args: argparse.Namespace) -> int:
    failed = False
    directory = Path(args.dir) if args.dir else plans_dir()
    for path in plan_files(directory):
        try:
            problems = check_plan(read_plan(path))
        except ValueError as e:
            problems = [str(e)]
        print(f"{path.name}: {'ok' if not problems else ''}")
        for p in problems:
            print(f"  {p}")
        failed |= bool(problems)
    for code in set(read_index(directory)) - {p.stem for p in plan_files(directory)}:
        print(f"{INDEX}: {code} has no {code}.csv")
        failed = True
    return 1 if failed else 0


def _list(args: argparse.Namespace) -> int:
    rows = search(load_bank(Path(args.dir) if args.dir else None), race=args.race, discipline=args.discipline,
                  weeks_to_race=args.weeks_to_race, phase=args.phase)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[x.name for x in fields(BankWorkout)])
            writer.writeheader()
            writer.writerows(asdict(r) for r in rows)
        print(f"{len(rows)} workouts written to {args.csv}")
    else:
        for r in rows:
            print(f"{r.code:<18} {r.phase:<6} {r.duration_min:>3} min  z{r.intensity}  {r.description}")
        print(f"{len(rows)} workouts")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m flextri.bank", description="The workout bank.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("code", help="fill in missing workout codes in a plan CSV")
    p.add_argument("plan")
    p.set_defaults(func=_code)
    p = sub.add_parser("check", help="check every plan in the bank")
    p.add_argument("--dir", help="plans folder (default: the bundled plans)")
    p.set_defaults(func=_check)
    p = sub.add_parser("list", help="list or export bank workouts")
    p.add_argument("--dir", help="plans folder (default: the bundled plans)")
    p.add_argument("--race", choices=[d.value for d in Distance])
    p.add_argument("--discipline", choices=[d.value for d in Discipline])
    p.add_argument("--phase")
    p.add_argument("--weeks-to-race", type=int)
    p.add_argument("--csv", help="write the rows to this CSV file instead of printing them")
    p.set_defaults(func=_list)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
