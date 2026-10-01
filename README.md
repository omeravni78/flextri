# flexTri

Flexible triathlon coaching. Take a fixed-length plan (say 12 weeks), fit it to the
athlete's real timeline, and adapt it every day from what they actually did.

## Flow
1. **Onboarding** (`flextri onboard`): athlete, start date, race date, training days, max session length.
   The plan is stretched or compressed to the weeks available (`scaling.py`).
2. **Daily check-in** (`flextri today`, `flextri checkin`): record done / partial / missed,
   RPE, fatigue, soreness. Upcoming workouts adapt (`adaptation.py`).
3. **Closing ceremony** (`flextri finish`): summary of the block (`ceremony.py`).

## Try it
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
