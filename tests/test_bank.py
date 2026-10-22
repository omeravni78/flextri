"""The workout bank: plan CSVs, plan and workout codes, and the bank built from all bundled plans."""

import csv
from datetime import date

import pytest

from flextri import bank
from flextri.models import Athlete
from flextri.paths import bundled
from flextri.scaling import build_schedule
from flextri.storage import load_template

ROWS = [  # week, phase, day, slot, discipline, minutes
    (1, "base", "", "swim", "swim", 40),
    (1, "base", "", "run", "run", 30),
    (1, "base", "", "swim", "swim", 45),
    (2, "taper", "5", "", "strength", 20),
    (2, "taper", "2", "", "brick", 60),
]


def _write(folder, code="O_2_TP", rows=ROWS, race="olympic", weeks=2):
    with open(folder / bank.INDEX, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=bank.INDEX_COLUMNS)
        if f.tell() == 0:
            w.writeheader()
        w.writerow({"code": code, "name": "Test plan", "race": race, "weeks": weeks, "source": "test", "notes": ""})
    with open(folder / f"{code}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=bank.PLAN_COLUMNS)
        w.writeheader()
        for week, phase, day, slot, disc, mins in rows:
            w.writerow({"code": "", "week": week, "phase": phase, "day": day, "slot": slot, "discipline": disc,
                        "duration_min": mins, "intensity": 2, "key": "", "description": f"{disc} {mins}"})
    return folder / f"{code}.csv"


def test_codes_number_each_discipline_within_its_week(tmp_path):
    plan = bank.read_plan(_write(tmp_path))
    assert bank.assign_codes(plan) == 5
    assert [s["code"] for s in plan["weeks"][0]["sessions"]] == ["O_2_TP_W1_S1", "O_2_TP_W1_R1", "O_2_TP_W1_S2"]
    assert plan["weeks"][1]["days"]["2"][0]["code"] == "O_2_TP_W2_X1"  # fixed days go in day order
    assert plan["weeks"][1]["days"]["5"][0]["code"] == "O_2_TP_W2_G1"
    assert bank.check_plan(plan) == []


def test_existing_codes_are_never_renumbered(tmp_path):
    path = _write(tmp_path)
    assert bank.main(["code", str(path)]) == 0
    lines = path.read_text().splitlines()
    lines.insert(1, ",1,base,,swim,swim,30,2,,new swim")  # a new first row with no code yet
    path.write_text("\n".join(lines) + "\n")
    assert bank.main(["code", str(path)]) == 0
    codes = [s["code"] for s in bank.read_plan(path)["weeks"][0]["sessions"]]
    assert codes == ["O_2_TP_W1_S3", "O_2_TP_W1_S1", "O_2_TP_W1_R1", "O_2_TP_W1_S2"]


def test_plan_csv_round_trips(tmp_path):
    path = _write(tmp_path)
    plan = bank.read_plan(path)
    bank.write_plan(plan, path)
    assert bank.read_plan(path) == plan


def test_bad_plan_files_are_explained(tmp_path):
    with pytest.raises(ValueError, match="no row for O_2_XX"):
        bank.read_plan(tmp_path / "O_2_XX.csv")
    path = _write(tmp_path, rows=ROWS[:3])
    with pytest.raises(ValueError, match="no workouts in week"):
        bank.read_plan(path)


def test_check_finds_missing_wrong_and_duplicate_codes(tmp_path):
    plan = bank.read_plan(_write(tmp_path))
    bank.assign_codes(plan)
    week = plan["weeks"][0]["sessions"]
    week[1]["code"] = "O_2_TP_W1_S1"  # a run with a swim letter, and a duplicate
    week[2]["code"] = None
    problems = bank.check_plan(plan)
    assert any("does not fit O_2_TP_W1_R<n>" in p for p in problems)
    assert any("has no code" in p for p in problems)
    assert bank.check_plan({**plan, "code": "O_12_TP"}) != []  # code says 12 weeks, plan has 2


def test_check_and_list_commands(tmp_path, capsys):
    path = _write(tmp_path)
    assert bank.main(["check", "--dir", str(tmp_path)]) == 1  # no codes yet
    bank.main(["code", str(path)])
    assert bank.main(["check", "--dir", str(tmp_path)]) == 0
    assert bank.main(["list", "--dir", str(tmp_path), "--csv", str(tmp_path / "out.csv")]) == 0
    assert (tmp_path / "out.csv").read_text().count("\n") == 6  # header + 5 workouts


def test_bundled_plans_are_all_coded_and_unique():
    workouts = bank.load_bank()
    codes = [w.code for w in workouts]
    assert codes and len(codes) == len(set(codes))
    assert bank.main(["check"]) == 0


def test_bank_fields_and_search():
    workouts = bank.load_bank()
    swims = bank.search(workouts, plan_code="O_8_TRI", week=2, discipline="swim")
    assert [w.code for w in swims] == ["O_8_TRI_W2_S1", "O_8_TRI_W2_S2", "O_8_TRI_W2_S3"]
    assert {(w.plan_weeks, w.weeks_to_race, w.race, w.phase) for w in swims} == {(8, 6, "olympic", "base")}
    race = bank.search(workouts, slot="race")
    assert len(race) == 1 and race[0].weeks_to_race == 0 and race[0].key


def test_scheduled_workouts_keep_their_bank_code():
    template = load_template(bundled("plans", "O_8_TRI.csv"))
    assert template.code == "O_8_TRI"
    s = build_schedule(template, Athlete("omer", date(2026, 10, 5), date(2026, 11, 28)))
    assert all(w.workout.code and w.workout.code.startswith("O_8_TRI_W") for w in s.workouts)
