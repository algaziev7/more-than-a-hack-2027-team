# Almaz — Event tags and stoppages

- Owner: Almaz
- Status: first tagging module works locally; ready for Belek and Isken to review
- Branch: `almaz/tagging-v1`
- Reviewer: Belek and Isken
- Files: `possession/tagging.py`, its tests, and later `possession/dead_ball.py`
- Last update: 2026-10-24

## What is done

- The module reads event tags and creates team hints, weights, and restart clues
  for every frame. Belek and Isken will use these in their state machine.
- Unknown teams do not create a team preference. Conflicting team clues cancel.
  Repeated tags do not make the clue stronger.
- All 14 tests passed using invented events and a small invented XML file.
- Almaz ran `load_tagging_signals()` on his own XML and reported:
  `Created tagging signals for 199319 frames.`
- The usage guide is [TAGGING.md](../TAGGING.md). It explains how to load the
  clues once, keep them in memory, and read them inside the frame loop.
- No packages were installed. No pyenv or environment settings were changed.
- The code, tests, and docs are on review branch `almaz/tagging-v1`.
  They should be reviewed before merging into main.

## What to do next

1. Have Belek and Isken review the tagging pull request and TAGGING.md.
2. After review, merge the branch and connect the clues to their code.
3. Later, use Beks's movement features to improve detection of stoppages and
   restarts in `possession/dead_ball.py`.

## What is still missing

The current module does not decide whether play is stopped and does not produce
final possession labels. It supplies clues. The state machine must combine them
with other information.

We have not measured whether these clues improve possession accuracy. The
weights are starting choices; they were not chosen using the public answer file.

Azamat's new loader is not needed to use the tagging module. Beks's features
will be needed for the later stoppage detector.

## Checks and handoff

- Base commit: `22cb24b`. Review branch: `almaz/tagging-v1`, targeting main.
- Tests: `python3 -m unittest discover -s tests -p 'test_tagging.py' -v`.
  The recorded test run used the existing `/opt/homebrew/bin/python3` directly;
  all 14 passed. The test command does not need the match data.
- `git diff --check` passed.
- The output uses Python lists. Belek and Isken can use `np.asarray` if their
  code expects NumPy arrays. Details and examples are in TAGGING.md.
- The local XML run succeeded, but integration with the state machine and
  possession accuracy have not been checked.

Update this file with the code at each handoff. Keep actual XML contents and
match outputs out of this file, Git, and hosted AI chats.
