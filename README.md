# flexTri

Flexible triathlon coaching. Take a fixed-length plan (say 12 weeks), fit it to the
athlete's real timeline, and adapt it every day from what they actually did.

## Flow
1. **Onboarding** (`flextri onboard`): athlete, start date, race date, training days, max session length.
   The plan is stretched or compressed to the weeks available (`scaling.py`).
2. **Daily check-in** (`flextri today`, `flextri checkin`): record done / partial / missed,
   RPE, fatigue, soreness. Upcoming workouts adapt (`adaptation.py`).
3. **Closing ceremony** (`flextri finish`): summary of the block (`ceremony.py`).

## Install the app (no Python needed)
Download flexTri for Windows, macOS or Linux from the
[Releases page](https://github.com/omeravni78/flextri/releases) and follow [packaging/INSTALL.md](packaging/INSTALL.md).
Each release is built by `.github/workflows/app.yml` with PyInstaller (`packaging/flextri.spec`); push a tag such
as `v0.2.0` (after bumping `__version__`) to publish one. Pull requests that touch the app build all four downloads
as workflow artifacts, so they can be tried before merging.

Locally: `pip install -e ".[garmin,app,build]"`, then `python packaging/make_icons.py` and
`pyinstaller packaging/flextri.spec --noconfirm`; `dist/flexTri/flexTri --self-test` checks the result.

## Run from a checkout
`flextri-app` (or `python -m flextri.launcher`) starts the app, opens the browser and adds a tray icon.
On Windows, double-click `run-windows.bat`. The first run creates a `.venv` folder and installs flexTri
(Python 3.11+ from python.org is needed), then it opens http://127.0.0.1:8000 in your browser.
Close the window, or press Quit in the app, to stop it.

Or by hand, in PowerShell:
```
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn flextri.web.api:app --reload   # open http://127.0.0.1:8000
```
On macOS or Linux, the same steps with `source .venv/bin/activate`.
New athletes land on the 5-step setup wizard. After that, the home screen is **Today**, in the look the athlete
picked in the wizard's last step (switch any time from the bottom of the screen):

- **One Big Day**: today's minutes big on a sport-colored field, a day strip, and the check-in under your thumb.
- **Lane Lines**: today on top, the week below as pool lanes with each session drawn to its real length.
- **Coach Chat**: the plan talks to you like a coach; your check-in is a quick reply.

All three check in with one tap (Done, felt good / Done, felt hard / Cut it short / Skipped it) and show what that
changed in the days ahead, before and after, with "Change my answer" to undo it.

**Calendar** in the header is the 4-week calendar: tap a day to
ease, swap, move or rest a session, check in, or log an extra session. "Edit my setup" reopens the wizard and shows
what will change before saving. On a phone the calendar shows one week as a list with a 28-day strip on top.

## Send workouts to Garmin
Open **Garmin** in the header (or press "Send this week to Garmin" on the calendar), log in with your Garmin
Connect email and password, and enter the code if Garmin sends one. flexTri keeps only Garmin's login tokens,
never your password. "Send this week to watch" uploads the next 7 days of planned sessions; sync your watch to
get them. It needs the `garmin` extra: `pip install -e ".[garmin]"` (`run-windows.bat` installs it).

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

Data is one row in a local SQLite file, one athlete per install for now. It lives in the per-user data folder
(`%LOCALAPPDATA%\flexTri`, `~/Library/Application Support/flexTri`, `~/.local/share/flextri`) together with the
Garmin login tokens; `FLEXTRI_HOME` moves that folder, `FLEXTRI_DB` and `GARMINTOKENS` still override single paths.
On first start an older `flextri.db` in the current folder and tokens in `~/.garminconnect` are copied over.

## Try the CLI
```
pip install -e ".[dev]"
flextri onboard --template src/flextri/data/plans/olympic_8week_triathlete.json --name omer --start 2026-10-05 --race 2026-11-28 --days tue,wed,thu,sat,sun
flextri today --date 2026-10-07
flextri checkin --date 2026-10-07 --workout 2 --rpe 9 --fatigue 4
flextri finish
pytest
```

## Plans
Plans in `src/flextri/data/plans/` are offered in the setup wizard. `olympic_8week_triathlete.json` is Marilyn Chychota's free
[8-week Olympic plan](https://www.triathlete.com/training/8-week-triathlon-training-plan-olympic-distance/) from
Triathlete.com, with swims in meters.

A plan week can be written two ways:
- `"sessions"`: day-free. Each session has a `slot` (`swim`, `long_ride`, `long_run`, `brick`, `bike`, `run`,
  `strength`, `pre_race`, `race`). The athlete picks the long ride, long run, brick and swim days in the wizard;
  the rest is spread over their training days, at most 2 sessions a day and never the same sport twice in a day.
  With fewer training days than the plan needs, the key sessions and at least one swim, bike and run stay, and
  the easiest sessions are left out (the wizard says how many days the full plan needs). The race goes on
  race day and `pre_race` sessions the day before.
- `"days"`: fixed weekdays (`"0"` = Monday). Sessions move only when that day isn't a training day.

`src/flextri/data/examples/placeholder_plan.json` is a generic 4-week stand-in with fixed days, not real coaching content.
