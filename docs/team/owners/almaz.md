# Almaz — Event tags and stoppages

- Owner: Almaz
- Status: priors merged via PR #5; aggregate coverage follow-up ready for review
- Branch: `e3/prior-coverage-diagnostics`
- Reviewer: Beks and Belek/Isken; Azamat for shared types
- Files: `possession/dead_ball.py`, its tests, and related docs
- Last update: 2026-11-10

## Current follow-up: E2's low dead-ball coverage report

- Base: main `aa73103`, which includes E5 PR #10. E2 remains unmerged here;
  fetched/read `origin/e2/state-v1`'s current handoff before investigating.
- Worked in an isolated E3 worktree; the shared main checkout is unchanged.
- Added `summarize_prior_diagnostics` in E3's module. It reports totals and
  graded-frame shares for usable-ball/no-stop coverage, motion/stillness/context
  gates, incomplete dwell resets, confirmed stop runs and subsequent restarts.
  It compares stop support with/without E4 control corroboration. See the
  [local recipe and counter definitions](../DEAD_BALL.md#totals-only-coverage-diagnostics-2026-11-10).
- Code inspection and synthetic E4 integration establish that E4 control cannot
  remove E3 stop-support frames: stillness and live-motion gates are disjoint.
  Additional live support can affect E2's final D duration. This explains a
  possible mechanism, not the observed real-match reduction's measured cause.
- Missing/unusable observations reset stop dwell and context; stillness also
  requires a tag or outside-pitch clue. The dominant real-match coverage loss
  remains unmeasured. No restricted data or public labels were read or run.
- Shared contracts/signatures/config/defaults, tagging weights, prediction
  behavior and decoder fusion are unchanged. The new helper is opt-in.
  E2's proposed gap-only tag fusion remains E2-owned and needs E4 review.
- Verification: `python -m unittest tests.test_dead_ball` — 40 pass.
  `python -m unittest discover -s tests` — 134 discovered, 132 pass, two skips
  for the unmerged real decoder. Python 3.15.0 using the existing temporary
  environment/pinned dependencies; Python 3.12 remains unverified this session.
  `git diff --check` passed. Seven new tests cover gate totals, denominator
  semantics, missing/rejected-ball resets, half/lost-support resets, restart
  counting, real E4 stop invariance, additional live support and empty/disabled
  reports. No competition accuracy result is established.
- Next exact action: Belek/Beks review the diagnostic definitions and run the
  documented local recipe with the same prediction config. Share totals only.
  Compare prior stop support separately from final decoder D labels before
  proposing behavior changes. Do not tune against a desired stoppage count.
- Published implementation: `83d7bf7`, pushed to
  `origin/e3/prior-coverage-diagnostics`. PR creation was attempted but GitHub
  rejected `CreatePullRequest` for the connected account's permissions. A
  teammate with PR permission must open the branch's review PR, naming E2/E4
  as affected owners; no PR was created by this session.

## Historical handoff (2026-11-01, now merged)

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
