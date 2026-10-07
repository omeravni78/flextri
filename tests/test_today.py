from datetime import date

from flextri.today_view import brick_parts
from flextri.web import api

from test_ui import FORM, TODAY, client  # noqa: F401  (client is a fixture)

OLYMPIC = {**FORM, "plan": "olympic_8week_triathlete"}


def _store():
    return api.app.dependency_overrides[api.get_store]()


def _today_key(client):
    """Set up the Olympic plan and return today's (Wed 7 Oct) first session id."""
    client.post("/setup", data=OLYMPIC)
    s = _store().load()
    return next(w for w in s.on(TODAY) if w.workout.discipline.value != "rest")


def test_brick_parts_reads_the_plan_text():
    assert brick_parts("bike 40 min (12x15s fast/45s easy) + run 20 min easy off the bike") == [("bike", 40), ("run", 20)]
    assert brick_parts("core routine") is None


def test_home_is_today_in_the_chosen_look(client):
    client.post("/setup", data=OLYMPIC)
    home = client.get("/").text
    assert "lk-bigday" in home and "How did it go?" in home and 'href="/calendar"' in home
    for look, marker in [("lanes", "lane by lane"), ("chat", "flexTri coach")]:
        r = client.post("/look", data={"look": look})
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert marker in client.get("/").text
    assert _store().load().athlete.look == "chat"
    client.post("/look", data={"look": "neon"})  # unknown looks are ignored
    assert _store().load().athlete.look == "chat"


def test_wizard_picks_the_look(client):
    page = client.get("/setup").text
    assert "Your home screen" in page and 'name="look" value="lanes"' in page
    client.post("/setup", data={**OLYMPIC, "look": "lanes"})
    assert _store().load().athlete.look == "lanes"
    assert 'value="lanes" checked' in client.get("/setup").text


def test_hard_answer_eases_the_next_days_and_can_be_changed(client):
    sw = _today_key(client)
    before = [(w.id, w.workout.duration_min) for w in _store().load().upcoming(TODAY, 2)]
    html = client.post("/ui/today/checkin", data={"workout_id": sw.id, "choice": "hard"}).text
    assert "done, felt hard." in html and "next two days get lighter" in html and "Change my answer" in html
    s = _store().load()
    assert s.get(sw.id).status.value == "done" and s.checkins[-1].notes == "Done, felt hard"
    assert [(w.id, w.workout.duration_min) for w in s.upcoming(TODAY, 2)] != before

    html = client.post("/ui/today/undo").text
    s = _store().load()
    assert s.get(sw.id).status.value == "planned" and not s.checkins
    assert [(w.id, w.workout.duration_min) for w in s.upcoming(TODAY, 2)] == before
    assert "How did it go?" in html


def test_skipped_key_session_moves_with_before_and_after(client):
    client.post("/setup", data=OLYMPIC)
    store = _store()
    s = store.load()
    ride = next(w for w in s.workouts if w.workout.slot == "long_ride" and w.date >= TODAY)
    ride.date = TODAY  # the long ride is today, so skipping it has to move it
    store.save(s)
    client.post("/look", data={"look": "chat"})
    html = client.post("/ui/today/checkin", data={"workout_id": ride.id, "choice": "skip"}).text
    assert "Long ride is a key session, so it moves to Thu 8 Oct." in html
    assert "Long ride 120′, zone 2, moved here" in html and "Dropped to make room" in html
    assert store.load().get(ride.id).date == date(2026, 10, 8)


def test_checkin_rejects_bad_answers(client):
    sw = _today_key(client)
    assert "Pick how today" in client.post("/ui/today/checkin", data={"workout_id": sw.id, "choice": "meh"}).text
    client.post("/ui/today/checkin", data={"workout_id": sw.id, "choice": "good"})
    assert "already checked in" in client.post("/ui/today/checkin", data={"workout_id": sw.id, "choice": "good"}).text


def test_day_strip_shows_other_days(client):
    client.post("/setup", data=OLYMPIC)
    html = client.get("/ui/today?day=2026-10-10").text
    assert "Saturday 10 October" in html and "How did it go?" not in html


def test_old_installs_default_to_big_day():
    from flextri.storage import athlete_from_dict
    a = athlete_from_dict({"name": "x", "start_date": "2026-10-04", "race_date": "2026-12-27", "available_days": [1, 2, 3]})
    assert a.look == "bigday"
