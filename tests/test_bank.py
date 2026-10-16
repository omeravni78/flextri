"""The workout bank: plan and workout codes, and the bank built from all bundled plans."""

import json
from datetime import date

import pytest

from flextri import bank
from flextri.models import Athlete
from flextri.paths import bundled
from flextri.scaling import build_schedule
from flextri.storage import load_template


def _plan(**extra):
    return {
        "name": "Test plan", "race": "olympic", **extra,
        "weeks": [
            {"phase": "base", "sessions": [
                {"discipline": "swim", "duration_min": 40, "slot": "swim"},
                {"discipline": "run", "duration_min": 30, "slot": "run"},
                {"discipline": "swim", "duration_min": 45, "slot": "swim"},
            ]},
            {"phase": "taper", "days": {"5": [{"discipline": "strength", "duration_min": 20}],
                                        "2": [{"discipline": "brick", "duration_min": 60}]}},
        ],
    }


def test_codes_number_each_discipline_within_its_week():
    plan = _plan()
    assert bank.assign_codes(plan, "TP") == 5
    assert plan["code"] == "O_2_TP"
    assert [s["code"] for s in plan["weeks"][0]["sessions"]] == ["O_2_TP_W1_S1", "O_2_TP_W1_R1", "O_2_TP_W1_S2"]
    assert plan["weeks"][1]["days"]["2"][0]["code"] == "O_2_TP_W2_X1"  # fixed days go in day order
    assert plan["weeks"][1]["days"]["5"][0]["code"] == "O_2_TP_W2_G1"
    assert bank.check_plan(plan) == []


def test_existing_codes_are_never_renumbered():
    plan = _plan()
    bank.assign_codes(plan, "TP")
    plan["weeks"][0]["sessions"].insert(0, {"discipline": "swim", "duration_min": 30, "slot": "swim"})
    assert bank.assign_codes(plan) == 1
    assert [s["code"] for s in plan["weeks"][0]["sessions"]] == [
        "O_2_TP_W1_S3", "O_2_TP_W1_S1", "O_2_TP_W1_R1", "O_2_TP_W1_S2"]


def test_a_new_plan_needs_a_source_tag():
    with pytest.raises(ValueError, match="source"):
        bank.assign_codes(_plan())


def test_check_finds_missing_wrong_and_duplicate_codes():
    plan = _plan()
    bank.assign_codes(plan, "TP")
    week = plan["weeks"][0]["sessions"]
    week[1]["code"] = "O_2_TP_W1_S1"  # a run with a swim letter, and a duplicate
    del week[2]["code"]
    problems = bank.check_plan(plan)
    assert any("does not fit O_2_TP_W1_R<n>" in p for p in problems)
    assert any("has no code" in p for p in problems)
    assert bank.check_plan({**plan, "code": "O_12_TP"}) != []  # code says 12 weeks, plan has 2


def test_bundled_plans_are_all_coded_and_unique():
    workouts = bank.load_bank()
    codes = [w.code for w in workouts]
    assert codes and len(codes) == len(set(codes))


def test_bank_fields_and_search():
    workouts = bank.load_bank()
    swims = bank.search(workouts, plan_code="O_8_TRI", week=2, discipline="swim")
    assert [w.code for w in swims] == ["O_8_TRI_W2_S1", "O_8_TRI_W2_S2", "O_8_TRI_W2_S3"]
    assert {(w.plan_weeks, w.weeks_to_race, w.race, w.phase) for w in swims} == {(8, 6, "olympic", "base")}
    race = bank.search(workouts, slot="race")
    assert len(race) == 1 and race[0].weeks_to_race == 0


def test_two_plans_with_the_same_code_are_refused(tmp_path):
    for name in ("a.json", "b.json"):
        plan = _plan()
        bank.assign_codes(plan, "TP")
        (tmp_path / name).write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="already used by a.json"):
        bank.load_bank(tmp_path)


def test_code_command_writes_the_plan(tmp_path, capsys):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(_plan()))
    assert bank.main(["code", str(path), "--source", "tp"]) == 0
    plan = json.loads(path.read_text())
    assert list(plan)[:2] == ["name", "code"] and plan["code"] == "O_2_TP"
    assert bank.main(["check", "--dir", str(tmp_path)]) == 0
    assert bank.main(["list", "--dir", str(tmp_path), "--csv", str(tmp_path / "bank.csv")]) == 0
    assert (tmp_path / "bank.csv").read_text().count("\n") == 6  # header + 5 workouts


def test_scheduled_workouts_keep_their_bank_code():
    template = load_template(bundled("plans", "olympic_8week_triathlete.json"))
    assert template.code == "O_8_TRI"
    s = build_schedule(template, Athlete("omer", date(2026, 10, 5), date(2026, 11, 28)))
    assert all(w.workout.code and w.workout.code.startswith("O_8_TRI_W") for w in s.workouts)
