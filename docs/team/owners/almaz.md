# Almaz — Event tags and stoppages

- Owner: Almaz
- Status: first stoppage/restart prior implemented and tested; review pending
- Branch: `almaz/dead-ball-priors`
- Reviewer: Beks and Belek/Isken; Azamat for shared types
- Files: `possession/dead_ball.py`, its tests, and related docs
- Last update: 2026-11-01

## What is already merged

- PR #1: event tags become team hints and restart clues.
- PR #2: Azamat's loader and shared types.
- PR #3: Belek and Isken's validation plan.
- PR #4: tagging lists can be converted into the actual PriorData type.

## What this branch adds

`build_priors(match, features=None, config=None)` in possession/dead_ball.py:

- Combines existing tagging clues with sustained ball movement/position evidence.
- Supports stopped play when slow observations persist with a set-piece tag or
  an outside-pitch position. A stationary or missing ball alone is insufficient.
- Supports live play when in-pitch motion persists after a recent observed stop
  or alongside reliable control evidence from Beks.
- Emits at most one stronger restart pulse per confirmed stop. A motion pause
  cannot cause the same stop to produce another restart.
- Resets confirmation and restart context on missing/unusable observations and
  half changes. Excluded frames are neutral.
- Checks jumps, implausible positions, and disagreements between supplied speed
  and position-based movement. No missing-data interpolation or final labels.
- Returns the existing PriorData type. Shared types and Beks's feature keys
  are unchanged; features are optional until his module is ready.

## How the guys use it

```python
from possession.dead_ball import build_priors

priors = build_priors(match, features=features, config=config)
```

If features are not ready, call `build_priors(match)` instead. Read
[DEAD_BALL.md](../DEAD_BALL.md) for settings, reason codes, and timing. The
original tagging-only helpers remain available.

## Checks

- Base: `5219920`, merged tagging adapter PR #4.
- `python -m unittest discover -s tests -v`: all 97 tests passed, including
  33 new stoppage/restart tests. Inputs were invented; no match data or public
  answer file was read.
- Includes full-length output, half independence, repeated-restart regression,
  missing data, bad tracking, frame-rate timing, and unchanged input checks.
- `git diff --check` and dependency checks passed. Checked 16 Python examples,
  9 shell blocks, and 13 local documentation links; no real-data examples ran.
- Testing used a user-approved temporary environment with Python 3.15.0 and
  the existing locked dependencies. The team's Python 3.12 environment has not
  been tested for this branch. Pyenv and project environment are unchanged.

## Limits and next steps

The defaults are untuned heuristics, not measured probabilities. Actual referee
state cannot always be inferred from tracking and approximate tags. We have not
measured possession accuracy or run the full prediction pipeline.

1. Beks and Belek/Isken review the evidence rules and confirmation delay.
2. Review and merge this branch, then connect it to the state machine.
3. Run it locally on licensed data without sharing private arrays or extracts.
4. Use allowed validation to improve the method; never tune on public match GT.

Only this branch's work is implemented. No other owner's module was added.
