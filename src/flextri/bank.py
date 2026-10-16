"""The workout bank: every session from every bundled plan, each with a code saying where it came from.

Plan code:    <race>_<plan weeks>_<source>       e.g. O_8_TRI (Olympic, 8 weeks, Triathlete.com)
Workout code: <plan code>_W<week>_<discipline><n> e.g. O_8_TRI_W2_S1 (first swim of week 2)

A source that publishes a second version of a plan gets a number on its source tag (O_8_TRI2).
Codes are written into the plan file once by ``python -m flextri.bank code`` and never renumbered:
a new session gets the next free number, so a code keeps pointing at the same workout. The code is
only an ID; search the bank by its fields (race, weeks_to_race, discipline, ...), not by the code.

    python -m flextri.bank code PLAN.json --source TRI   # add missing codes to a plan file
    python -m flextri.bank check                         # validate codes in all bundled plans
    python -m flextri.bank list [--discipline swim] [--weeks-to-race 6] [--csv bank.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import paths
from .models import Discipline, Distance

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


def _week_sessions(week: dict) -> list[dict]:
    """A week's sessions in file order: fixed days first (by day), then day-free sessions."""
    days = week.get("days", {})
    return [s for day in sorted(days, key=int) for s in days[day]] + week.get("sessions", [])


def assign_codes(plan: dict, source: str | None = None) -> int:
    """Give the plan and every session without a code their code, in place. Returns how many were added.

    Existing codes are kept as they are; a new session takes the next free number for its
    discipline in that week, so nothing already in the bank is renumbered.
    """
    if not plan.get("code"):
        if not source:
            raise ValueError("plan has no code yet: pass the source tag, e.g. --source TRI")
        plan["code"] = plan_code(Distance(plan["race"]), len(plan["weeks"]), source)
    added = 0
    for i, week in enumerate(plan["weeks"], start=1):
        sessions = _week_sessions(week)
        prefix = f"{plan['code']}_W{i}_"
        taken = Counter()
        for s in sessions:
            if s.get("code", "").startswith(prefix):
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
    code = plan.get("code")
    if not code:
        return ["plan has no code"]
    problems = []
    if not PLAN_CODE.match(code):
        problems.append(f"plan code {code} is not <race>_<weeks>_<source>")
    if plan.get("race") not in {d.value for d in Distance}:
        problems.append(f"plan race {plan.get('race')!r} is not one of {[d.value for d in Distance]}")
    elif not code.startswith(plan_code(Distance(plan["race"]), len(plan["weeks"]), "")):
        problems.append(f"plan code {code} does not match race {plan['race']} and {len(plan['weeks'])} weeks")
    seen = set()
    for i, week in enumerate(plan["weeks"], start=1):
        for s in _week_sessions(week):
            c = s.get("code")
            letter = DISCIPLINE_LETTERS[Discipline(s["discipline"])]
            if not c:
                problems.append(f"week {i}: {s['discipline']} '{s.get('description', '')}' has no code")
            elif not re.fullmatch(rf"{re.escape(code)}_W{i}_{letter}\d+", c):
                problems.append(f"week {i}: {c} does not fit {code}_W{i}_{letter}<n>")
            elif c in seen:
                problems.append(f"{c} is used twice")
            seen.add(c)
    return problems


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
        for s in _week_sessions(week)
    ]


def plans_dir() -> Path:
    return Path(paths.bundled("plans"))


def load_bank(directory: Path | None = None) -> list[BankWorkout]:
    """Every workout from every plan in the folder. Raises if a plan's codes are missing or clash."""
    bank, owner = [], {}
    for path in sorted((directory or plans_dir()).glob("*.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        if problems := check_plan(plan):
            raise ValueError(f"{path.name}: " + "; ".join(problems))
        if plan["code"] in owner:
            raise ValueError(f"{path.name}: plan code {plan['code']} is already used by {owner[plan['code']]}")
        owner[plan["code"]] = path.name
        bank.extend(bank_from_plan(plan))
    return bank


def search(bank: list[BankWorkout], **filters) -> list[BankWorkout]:
    """Workouts whose fields equal every given filter, e.g. search(bank, discipline="swim", weeks_to_race=6)."""
    return [w for w in bank if all(getattr(w, k) == v for k, v in filters.items() if v is not None)]


def _code(args: argparse.Namespace) -> int:
    path = Path(args.plan)
    plan = json.loads(path.read_text(encoding="utf-8"))
    added = assign_codes(plan, args.source)
    plan = {"name": plan["name"], "code": plan["code"], **plan}  # keep the code near the top of the file
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{path.name}: plan {plan['code']}, {added} workout code(s) added")
    return 0


def _check(args: argparse.Namespace) -> int:
    failed = False
    for path in sorted(Path(args.dir or plans_dir()).glob("*.json")):
        problems = check_plan(json.loads(path.read_text(encoding="utf-8")))
        print(f"{path.name}: {'ok' if not problems else ''}")
        for p in problems:
            print(f"  {p}")
        failed |= bool(problems)
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
    p = sub.add_parser("code", help="add missing plan and workout codes to a plan file")
    p.add_argument("plan")
    p.add_argument("--source", help="short source tag for a plan with no code yet, e.g. TRI")
    p.set_defaults(func=_code)
    p = sub.add_parser("check", help="check the codes in every plan")
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
