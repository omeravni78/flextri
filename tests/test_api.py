from datetime import date

import pytest
from fastapi.testclient import TestClient

from flextri.storage import SqliteStore
from flextri.web import api

TODAY = date(2026, 10, 7)  # a Wednesday

PROFILE = {
    "name": "omer", "experience": "some", "weekly_hours": 6, "race_date": "2026-12-27",
    "distance": "olympic", "goal": "finish", "start_date": "2026-10-04", "week_start": 6,
    "available_days": [1, 2, 3, 5, 6], "max_weekday_min": 60, "max_weekend_min": 120,
}


@pytest.fixture
def client(tmp_path):
    store = SqliteStore(tmp_path / "t.db")
    api.app.dependency_overrides[api.get_store] = lambda: store
    api.app.dependency_overrides[api.get_today] = lambda: TODAY
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_wizard_validation(client):
    bad = {**PROFILE, "available_days": [1, 2]}
    assert client.put("/api/profile", json=bad).status_code == 422
    bad = {**PROFILE, "race_date": "2026-10-10"}
    assert client.put("/api/profile", json=bad).status_code == 422
    assert client.get("/api/calendar").status_code == 404


def test_full_flow(client):
    preview = client.post("/api/profile/preview", json=PROFILE).json()
    assert preview["fitted_weeks"] == 13 and preview["plan_weeks"] == 4

    assert client.put("/api/profile", json=PROFILE).status_code == 200
    cal = client.get("/api/calendar").json()
    assert len(cal["weeks"]) == 4
    first = cal["weeks"][0]
    assert first["first_day"] == "2026-10-04" and first["number"] == 1
    days = first["days"]
    assert date.fromisoformat(days[0]["date"]).weekday() == 6
    assert days[3]["is_today"] and not days[2]["editable"]

    wed = next(s for s in days[3]["sessions"] if s["key"])
    assert wed["can_swap_to"] == []
    r = client.post("/api/days/2026-10-07/actions", json={"kind": "easier", "workout_id": wed["id"]})
    assert r.status_code == 200 and r.json()["changes"]

    r = client.post("/api/days/2026-10-07/actions", json={"kind": "swap", "workout_id": wed["id"], "discipline": "run"})
    assert r.status_code == 400 and "Key sessions" in r.json()["detail"]

    assert client.post("/api/undo").status_code == 200
    r = client.post("/api/checkins", json={"date": "2026-10-07", "workout_id": wed["id"], "rpe": 9, "fatigue": 4})
    assert r.status_code == 200 and any("Eased" in c for c in r.json()["changes"])
    assert client.post("/api/checkins", json={"date": "2026-10-01"}).status_code == 400

    edit = {**PROFILE, "race_date": "2027-01-10"}
    assert client.post("/api/profile/preview", json=edit).json()["changes"][0] == "2 weeks added"
    assert client.put("/api/profile", json=edit).status_code == 200
    assert client.get("/api/profile").json()["race_date"] == "2027-01-10"

    summary = client.get("/api/summary").json()
    assert summary["sessions_done"] == 1
