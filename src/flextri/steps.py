"""The steps of a workout, written in a short text format in the plan CSV's ``steps`` column.

Plans describe sessions in free text ("easy with 8x30s hill strides"), which is fine for a
person but leaves out what a watch needs: how long each part is, how many repeats, how long
to recover. The ``steps`` column spells that out once, when a plan is added, so the Garmin
workout can show the real session:

    wu 10min z1; * z2; 8x(30s [hill stride, fast], 90s z1 [jog back down]); cd 5min z1

Steps are separated by ``;``. Each step is

    kind amount zone [note]

where only the amount is required.

- kind: ``wu`` warm-up, ``cd`` cool-down, ``rec`` recovery, ``rest`` (a swim's rest at the
  wall); without one the step is the main work.
- amount: minutes ``10min``, seconds ``30s``, both ``1min30s``, meters ``400m``, ``lap``
  (until the lap button is pressed), or ``*``: whatever time is left of the session, so a plan
  that flexTri stretches or squeezes still adds up.
- zone: heart rate zone ``z1`` .. ``z5``; leave it out for strides and drills, where heart
  rate can't keep up.
- note, in square brackets: shown on the watch for that step.

``8x(a, b)`` repeats the steps inside, which are separated by commas. A brick has one list
per sport: ``bike: ... | run: ...``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KINDS = {"wu": "warmup", "cd": "cooldown", "rec": "recovery", "rest": "rest"}

_TOKEN = re.compile(r"\s*(\[[^\]]*\]|\d+x\(|[(),;*]|[^\s(),;\[\]]+)")
_TIME = re.compile(r"^(?:(\d+)min)?(?:(\d+)s)?$")
_METERS = re.compile(r"^(\d+)m$")
_ZONE = re.compile(r"^z([1-5])$")


@dataclass
class Step:
    kind: str = "interval"  # warmup, cooldown, interval, recovery or rest
    seconds: int | None = None
    meters: int | None = None
    lap: bool = False
    fill: bool = False  # takes the session's remaining time
    zone: int | None = None
    note: str = ""


@dataclass
class Repeat:
    times: int
    steps: list[Step | Repeat] = field(default_factory=list)


Steps = list[Step | Repeat]


def _tokens(text: str) -> list[str]:
    tokens, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip():
                raise ValueError(f"can't read {text[pos:]!r}")
            break
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


def _step(words: list[str]) -> Step:
    step = Step()
    rest = list(words)
    if rest and rest[0] in KINDS:
        step.kind = KINDS[rest.pop(0)]
    if not rest:
        raise ValueError(f"step {' '.join(words)!r} has no amount")
    amount = rest.pop(0)
    if amount == "*":
        step.fill = True
    elif amount == "lap":
        step.lap = True
    elif m := _METERS.match(amount):
        step.meters = int(m.group(1))
    elif (m := _TIME.match(amount)) and amount:
        step.seconds = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    else:
        raise ValueError(f"{amount!r} is not a length like 10min, 30s, 400m, lap or *")
    for word in rest:
        if m := _ZONE.match(word):
            step.zone = int(m.group(1))
        elif word.startswith("["):
            step.note = word[1:-1].strip()
        else:
            raise ValueError(f"don't know {word!r} in step {' '.join(words)!r}")
    return step


def _parse(tokens: list[str], pos: int, sep: str, end: str | None) -> tuple[Steps, int]:
    out: Steps = []
    words: list[str] = []

    def flush() -> None:
        if words:
            out.append(_step(words))
            words.clear()

    while pos < len(tokens):
        t = tokens[pos]
        if t.endswith("x("):
            if words:
                raise ValueError(f"{' '.join(words)!r} runs into a repeat; separate them with {sep!r}")
            inner, pos = _parse(tokens, pos + 1, ",", ")")
            if not inner:
                raise ValueError("empty repeat")
            out.append(Repeat(int(t[:-2]), inner))
            continue
        if t == end:
            flush()
            return out, pos + 1
        if t == sep:
            flush()
        elif t in "(),;":
            raise ValueError(f"unexpected {t!r}")
        else:
            words.append(t)
        pos += 1
    if end:
        raise ValueError("a repeat is missing its ')'")
    flush()
    return out, pos


def parse(text: str) -> Steps:
    """Steps from the text format; raises ValueError saying what is wrong."""
    steps, _ = _parse(_tokens(text), 0, ";", None)
    if sum(1 for s in walk(steps) if s.fill) > 1:
        raise ValueError("only one step can be '*'")
    return steps


def legs(text: str) -> dict[str, Steps]:
    """A brick's steps per sport: {"bike": [...], "run": [...]}."""
    out = {}
    for part in text.split("|"):
        sport, colon, rest = part.partition(":")
        if not colon or sport.strip() not in ("bike", "run", "swim"):
            raise ValueError(f"brick steps need 'bike: ... | run: ...', got {part.strip()!r}")
        out[sport.strip()] = parse(rest)
    return out


def walk(steps: Steps):
    for s in steps:
        if isinstance(s, Repeat):
            yield from walk(s.steps)
        else:
            yield s


def fixed_seconds(steps: Steps) -> int:
    """Time of the steps with a set time, repeats counted; distance, lap and '*' steps count 0."""
    total = 0
    for s in steps:
        if isinstance(s, Repeat):
            total += s.times * fixed_seconds(s.steps)
        elif s.seconds:
            total += s.seconds
    return total


def has_fill(steps: Steps) -> bool:
    return any(s.fill for s in walk(steps))


def check(text: str, discipline: str) -> None:
    """Raise ValueError if ``text`` isn't valid steps for this discipline."""
    if discipline == "brick":
        legs(text)
    elif discipline in ("swim", "bike", "run"):
        parse(text)
    else:
        raise ValueError(f"{discipline} sessions aren't sent to a watch, so they take no steps")
