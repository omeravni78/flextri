---
name: add-plan
description: Turn a training plan the user sends (text, screenshot, PDF or link) into a coded plan CSV in the workout bank and open a PR. Use whenever the user shares a plan to add.
---

# Add a plan to the workout bank

Plans live in `src/flextri/data/plans/`: `plans.csv` lists them and each plan is `<code>.csv`, one row per
workout. The README section "Workout bank and codes" has the scheme; `src/flextri/bank.py` has the format.

## 1. Read the plan
- Work out the race (`sprint`, `olympic`, `70.3`, `full`), the number of weeks, the source (author, site, URL) and
  each week's phase (`base`, `build`, `peak`, `taper`). If the source doesn't name phases, assign them: the last
  1-2 weeks are taper, then peak, build and base going backwards.
- If something can't be read (a blurry screenshot, a missing week), ask the user about that part only.

## 2. Pick the plan code
`<race letter>_<weeks>_<source tag>`: race letters `S` sprint, `O` olympic, `H` 70.3, `I` full. The source tag is
2-4 capital letters for the publisher (e.g. `TRI` for Triathlete.com). Check `plans.csv`: if the code is taken by a
different plan from the same source, add a number (`O_8_TRI2`). Never reuse or change an existing code.

## 3. Write the files
- Add a row to `plans.csv`: `code, name, race, weeks, source, notes`. Notes say what was converted
  (e.g. yards to meters) and anything the athlete should know.
- Write `<code>.csv` with the header
  `code,week,phase,day,slot,discipline,duration_min,intensity,key,description,steps`, leaving `code` empty.
  - `discipline`: `swim`, `bike`, `run`, `brick`, `strength`, `rest`.
  - Plans must not hard-code weekdays: leave `day` empty and give every row a `slot`: `swim`, `long_ride`,
    `long_run`, `brick`, `bike`, `run`, `strength`, `pre_race`, `race`. The week's longest ride and run are the
    long ones. Only fill `day` (0 = Mon .. 6 = Sun) if the user asks for fixed days.
  - `duration_min`: minutes. If the source gives only distance, estimate the minutes and keep the distance in the
    description.
  - `intensity`: zone 1-5 (easy 2, steady 3, tempo/threshold 4, VO2/race-pace 5).
  - `key`: `yes` for the week's long ride, long run, brick and hard interval sessions; otherwise empty.
  - `description`: the session as written, short. Swims in meters (yards x 0.9144, rounded to 50 m).
  - Every week needs at least one row; the final week ends with a `race` row (`key` yes, `duration_min` 0).
  - `steps`: for every swim, bike, run and brick, the session as the watch should run it, in the format in
    `src/flextri/steps.py`, e.g. `* z2 [easy]; 8x(30s [hill stride], 90s z1 [jog back down]); cd 5min z1`.
    Swims in meters, no zones. Give one easy or steady step `*` so the session still adds up when flexTri
    stretches it (leave `*` out when the session has distance steps). Bricks: `bike: ... | run: ...`, each leg
    adding up to its minutes in the description. Where the source leaves something out (recoveries, warm-up),
    pick a sensible default and list those defaults in the PR. Leave it empty for strength, rest and race rows.

## 4. Fill in codes and check
```
python -m flextri.bank code src/flextri/data/plans/<code>.csv
python -m flextri.bank check
python -m pytest -q
```
(Install first with `pip install -e ".[dev,garmin]"`.) `code` only fills empty codes; existing codes never change.

## 5. Open the PR
Branch `plan/<code>` from `develop`, one commit, PR to `develop`. In the PR description, give the plan name, the
source link, the weeks and phases, and any assumptions you made (estimated minutes, phases you assigned). Ask the
user to look over the CSV in the PR before merging.
