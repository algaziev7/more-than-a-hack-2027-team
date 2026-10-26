# Almaz — Event tags and stoppages

- Owner: Almaz
- Status: tagging adapter implemented and tested locally; review pending
- Branch: `almaz/tagging-adapter`
- Reviewer: Belek and Isken; Azamat for the shared data format
- Files: `possession/tagging.py`, tagging tests, and related docs
- Last update: 2026-10-26

## What is already merged

- PR #1 added team hints, weights, and restart clues from event tags.
- PR #2 added Azamat's data loader and shared types, including `PriorData`.
- Almaz previously ran the original tagging helper on his local XML and
  reported 199,319 output frames. No match contents were shared.

## What this branch adds

- `to_prior_data(signals)` converts existing tagging lists into Azamat's
  checked NumPy arrays. It preserves every clue, weight, and reason code.
- `build_tagging_priors(events, n_frames, config=None)` builds the clues and
  converts them in one call. Belek and Isken can use it with `match.events`.
- Incorrect frame order, mismatched lengths, invalid values, and non-integer
  reason codes cause errors. Empty inputs work. Returned arrays are independent
  copies, so other code cannot accidentally change the source signals.
- The original list-based helper still works without NumPy.
- Eleven new tests check this adapter against Azamat's actual `PriorData` and
  shared synthetic match fixture. All 54 relevant tests passed.
- TAGGING.md now shows the recommended call and a complete invented example.
  INTERFACES.md and SETUP.md explain how the modules connect.
- Review branch: `almaz/tagging-adapter`, targeting main. The adapter needs
  review before it is merged and used by the team.

## How the guys use it

After Azamat's loader returns `match`:

```python
from possession.tagging import build_tagging_priors

priors = build_tagging_priors(match.events, n_frames=len(match.frame))
```

Pass `priors` into the state machine alongside Beks's features. See
[TAGGING.md](../TAGGING.md) for the full steps.

## Checks

- Base commit: `b29d8b7` (Azamat's merged PR #2).
- Command: `python -m unittest tests.test_tagging tests.test_tagging_adapter
  tests.test_contracts tests.test_data -v` — 54 passed.
- Tests used invented inputs only, including the real shared contracts and
  Azamat's existing loader tests. No restricted data or public answer file
  was read for this adapter work.
- With user approval, testing used a temporary environment under /private/tmp
  with Python 3.15.0 and NumPy 2.5.4. No pyenv, project environment, or dependency
  lock changes were made. A run in the team's Python 3.12 environment is still
  a separate check.
- No performance improvement or possession accuracy has been measured.

## What to do next

1. Have Belek, Isken, and Azamat review the adapter pull request.
2. Belek and Isken connect the returned `PriorData` to their state machine.
3. Agree with Beks on movement features for a later stoppage detector.

The adapter does not detect actual dead balls. Its dead-ball fields remain
neutral. That later work belongs in `possession/dead_ball.py`.

Keep this file updated with the code. Keep actual match data and outputs out
of Git and hosted AI chats.
