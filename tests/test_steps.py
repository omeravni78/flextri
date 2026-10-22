from datetime import date

import pytest

from flextri import bank, steps
from flextri.garmin import to_garmin_workouts
from flextri.models import Discipline, Phase, ScheduledWorkout, Workout

STRIDES = "* z2 [easy]; 8x(30s [hill stride, fast but relaxed], 90s z1 [jog back down]); cd 5min z1"


def _sw(discipline, minutes, intensity, desc, code):
    return ScheduledWorkout(id=1, date=date(2026, 10, 26), phase=Phase.BASE,
                            workout=Workout(discipline, minutes, intensity, desc, code=code))


def test_parse_reads_kinds_amounts_zones_notes_and_repeats():
    fill, repeat, cd = steps.parse(STRIDES)
    assert (fill.fill, fill.zone, fill.note) == (True, 2, "easy")
    assert repeat.times == 8
    assert repeat.steps[0] == steps.Step(seconds=30, note="hill stride, fast but relaxed")
    assert repeat.steps[1] == steps.Step(seconds=90, zone=1, note="jog back down")
    assert (cd.kind, cd.seconds) == ("cooldown", 300)
    assert steps.fixed_seconds(steps.parse(STRIDES)) == 21 * 60
    [swim] = steps.parse("rest 1min30s; 400m [pull]; lap")[1:2]
    assert swim.meters == 400
    assert steps.parse("wu 1min30s")[0].seconds == 90


@pytest.mark.parametrize("text", ["8x(30s", "10min z9", "wu", "2x()", "* z2; * z1", "30s [a] b", "10 min"])
def test_parse_says_what_is_wrong(text):
    with pytest.raises(ValueError):
        steps.parse(text)


def test_brick_legs_and_check():
    legs = steps.legs("bike: 40min z2 | run: 20min z2")
    assert list(legs) == ["bike", "run"]
    with pytest.raises(ValueError):
        steps.check("40min z2", "brick")
    with pytest.raises(ValueError):
        steps.check("20min", "strength")


def test_strides_run_reaches_garmin_as_written():
    """The run from omer's test: 40 min, zone 2, 'easy with 8x30s hill strides'."""
    [p] = to_garmin_workouts(_sw(Discipline.RUN, 40, 2, "easy with 8x30s hill strides", "O_8_TRI_W1_R2"))
    easy, repeat, cd = p["workoutSegments"][0]["workoutSteps"]
    assert (easy["endConditionValue"], easy["zoneNumber"]) == (19 * 60, 2)  # what's left after strides and cool-down
    assert repeat["type"] == "RepeatGroupDTO" and repeat["numberOfIterations"] == 8
    stride, back = repeat["workoutSteps"]
    assert (stride["endConditionValue"], stride["targetType"]["workoutTargetTypeKey"]) == (30, "no.target")
    assert stride["description"] == "hill stride, fast but relaxed"
    assert (back["stepType"]["stepTypeKey"], back["endConditionValue"], back["zoneNumber"]) == ("interval", 90, 1)
    assert [s["stepOrder"] for s in (easy, repeat, stride, back, cd)] == [1, 2, 3, 4, 5]
    assert stride["childStepId"] == back["childStepId"] == repeat["childStepId"]
    assert cd["stepType"]["stepTypeKey"] == "cooldown"
    assert p["estimatedDurationInSecs"] == 40 * 60


def test_stretched_session_gives_the_extra_time_to_the_star_step():
    [p] = to_garmin_workouts(_sw(Discipline.RUN, 50, 2, "easy with 8x30s hill strides", "O_8_TRI_W1_R2"))
    assert p["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"] == 29 * 60


def test_eased_or_too_short_sessions_fall_back_to_plain_steps():
    eased = _sw(Discipline.RUN, 45, 2, "6x90s uphill efforts", "O_8_TRI_W1_R3")  # the plan has it in zone 3
    squeezed = _sw(Discipline.RUN, 20, 2, "easy with 8x30s hill strides", "O_8_TRI_W1_R2")
    for sw in (eased, squeezed):
        [p] = to_garmin_workouts(sw)
        kinds = [s["stepType"]["stepTypeKey"] for s in p["workoutSegments"][0]["workoutSteps"]]
        assert kinds in (["warmup", "interval", "cooldown"], ["interval"])


def test_swim_steps_are_distances_without_heart_rate():
    [p] = to_garmin_workouts(_sw(Discipline.SWIM, 20, 2, "900 m: drills, descending pace, paddle work",
                                 "O_8_TRI_W1_S1"))
    wu = p["workoutSegments"][0]["workoutSteps"][0]
    assert (wu["endCondition"]["conditionTypeKey"], wu["endConditionValue"]) == ("distance", 200)
    assert all("zoneNumber" not in s for s in p["workoutSegments"][0]["workoutSteps"])


def test_brick_legs_take_their_own_steps_and_minutes():
    desc = "bike 40 min (12x15s fast/45s easy) + run 20 min easy off the bike"
    bike, run = to_garmin_workouts(_sw(Discipline.BRICK, 60, 3, desc, "O_8_TRI_W3_X1"))
    assert bike["workoutSegments"][0]["workoutSteps"][1]["numberOfIterations"] == 12
    assert (bike["estimatedDurationInSecs"], run["estimatedDurationInSecs"]) == (40 * 60, 20 * 60)


def test_every_plan_session_with_steps_is_valid():
    for path in bank.plan_files():
        assert bank.check_plan(bank.read_plan(path)) == []


def test_check_reports_bad_steps(tmp_path):
    plan = bank.read_plan(bank.plan_files()[0])
    plan["weeks"][0]["sessions"][0]["steps"] = "8x(30s"
    assert any("steps" in p for p in bank.check_plan(plan))
