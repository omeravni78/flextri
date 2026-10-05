# flexTri

Flexible triathlon coaching. Take a fixed-length plan (say 12 weeks), fit it to the
athlete's real timeline, and adapt it every day from what they actually did.

## Flow
1. **Onboarding** (`flextri onboard`): athlete, start date, race date, training days, max session length.
   The plan is stretched or compressed to the weeks available (`scaling.py`).
2. **Daily check-in** (`flextri today`, `flextri checkin`): record done / partial / missed,
   RPE, fatigue, soreness. Upcoming workouts adapt (`adaptation.py`).
3. **Closing ceremony** (`flextri finish`): summary of the block (`ceremony.py`).

## Run the app
```
pip install -e '.[dev]'
uvicorn flextri.web.api:app --reload   # open http://127.0.0.1:8000
```
New athletes land on the 5-step setup wizard. After that, the home screen is the 4-week calendar: tap a day to
ease, swap, move or rest a session, check in, or log an extra session. "Edit my setup" reopens the wizard and shows
what will change before saving. On a phone the calendar shows one week as a list with a 28-day strip on top.

## Web API (behind the wizard and calendar screens)
```
uvicorn flextri.web.api:app --reload   # API docs at http://127.0.0.1:8000/docs
```
| Endpoint | What it does |
| --- | --- |
| `POST /api/profile/preview` | Wizard step 4: how the plan fits, and what an edit would change |
| `PUT /api/profile` | Wizard confirm, or "Edit my setup" (past days never change) |
| `GET /api/calendar?around=YYYY-MM-DD` | 4 weeks from the athlete's chosen first weekday |
| `POST /api/days/{date}/actions` | `easier`, `swap` (easy sessions only), `move` (same week), `rest`, `add` |
| `POST /api/undo` | Undo the last day action |
| `POST /api/checkins` | Daily check-in (today or up to 2 days back) |
| `GET /api/summary` | Closing ceremony numbers |

Data is one row in a local SQLite file (`FLEXTRI_DB`, default `flextri.db`); one athlete per install for now.

## Try the CLI
```
pip install -e '.[dev]'
flextri onboard --template examples/placeholder_plan.json --name omer \
  --start 2026-10-05 --race 2026-12-27 --days tue,wed,thu,sat,sun
flextri today --date 2026-10-07
flextri checkin --date 2026-10-07 --workout 2 --rpe 9 --fatigue 4
flextri finish
pytest
```

`examples/placeholder_plan.json` is a generic 4-week stand-in, not real coaching content.
The real plan goes in the same JSON format when it's ready.
