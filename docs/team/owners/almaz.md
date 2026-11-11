# Almaz — Event tags and stoppages

- Owner: Almaz
- Status: priors merged via PR #5; PR #11 review correction verified; ready for E2/E4 re-review
- Branch: `e3/prior-coverage-diagnostics`
- Reviewer: Beks and Belek/Isken; Azamat for shared types
- Files: `possession/dead_ball.py`, its tests, and related docs
- Last update: 2026-11-11

## Integrated candidate handoff (2026-11-11)

- `e2/possession-refinement` integrates this fixed PR #11 with PR #13 and new
  decoder policies. `configs/possession-v2.json` explicitly enables 0.2 s missing
  tolerance; E3's default remains zero for existing configurations.
- Combined suite: 228 pass, no skips, including repeated-gap restart preservation
  and a full-length invented pipeline/export/manifest. Python 3.15.0; no match
  assets or public labels used. Shared prior fields/signature unchanged.
- See the [refinement decision](../decisions/2026-11-11-possession-refinement.md)
  for live/unknown assignment, boundary limits, evidence and limitations.
- Next: E2/E3/E4 review the candidate; authorised local runs and independent
  reproduction remain required. This is branch work, not accepted main behavior.

## Current follow-up: E2's low dead-ball coverage report

### PR #11 review correction (2026-11-11)

- Addressed [Belek's inline review](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/11#discussion_r4536514399)
  on branch `e3/prior-coverage-diagnostics`, based on `9c1daf4`.
- The cumulative missing-frame budget now applies only while confirmation is
  pending and clears on confirmation. Confirmed stops retain the per-gap bound;
  repeated isolated gaps no longer erase a long stop or its restart context.
  Missing frames remain neutral; long gaps, rejected observations, displacement
  checks and half resets retain their existing behavior. Default gap remains 0.
- Clarified the review nit: `confirmed_stop_frames_overwritten_by_live` is a
  structural invariant check, required to be zero by disjoint speed gates.
  No shared contracts or signatures changed; E2/E4 are the affected consumers.
- Added three synthetic regressions, all reproduced failing before the fix:
  a long stop with repeated gaps, restart after the former budget reset, and
  confirmation after exhausting the pending budget. All now pass.
- Verification with the existing Python 3.15.0 environment:
  `python -m unittest tests.test_dead_ball`: 53 pass;
  `python -m unittest discover -s tests`: 147 discovered, 145 pass, two existing
  decoder skips on this branch; `git diff --check`: pass.
- Combined verification: archived main `7431a44` into a disposable directory,
  overlaid this branch's `possession/dead_ball.py` and `tests/test_dead_ball.py`,
  initialized Git for repository-policy tests, then ran the full suite:
  **200 pass, no skips**, including the real decoder integration tests.
  The initial archive-only run failed Git-dependent ignore checks because it
  lacked `.git`; initializing the disposable repository resolved those failures.
- No restricted inputs, public labels or real-match jobs used. Python 3.12 and
  competition accuracy remain unverified in this session. Shared main untouched.
- Next: E2/E4 re-review PR #11's corrected gap semantics; an authorised teammate
  performs the documented local comparison before choosing a gap setting.


### Bounded-gap candidate added after the diagnostic increment

- Implemented opt-in `dead_ball.max_missing_gap_s` (default 0, original policy).
  Synthetic candidate: 0.2 s, not selected from match counts or labels.
  Retain stop support across a bounded total missing-frame budget; count only
  observed candidates. Preserve recent stop context across short occlusions,
  require fresh consecutive live motion, check reacquisition displacement,
  and reset on rejected samples, exhausted budget and half boundaries.
- No shared fields/signatures or E2 fusion changes. E2/E4 must review the new
  configuration's behavior before choosing it for submission. The main
  coverage bottleneck is still unmeasured; this addresses one explicit failure
  mode rather than establishing a complete stoppage detector.
- Ten synthetic tests added: short/long/repeated gaps, no missing-only stop,
  reacquisition elsewhere, rejected samples, restart timing, half reset,
  FPS-aware budget limits, validation and aggregate diagnostics. E3 suite:
  50 pass on the existing Python 3.15 environment.
- Full suite: 144 discovered, 142 pass, two real-decoder integration skips;
  `git diff --check` passes. PR creation remains blocked by the previously
  reported GitHub permission; the candidate is published on this task branch.
- Next: run aggregate diagnostics locally with gap setting 0 and 0.2 using
  the same remaining config, then review the evidence and tradeoffs in
  DEAD_BALL.md with Belek/Beks. No match run was performed by the assistant.

### Original diagnostic increment (behavior unchanged at gap setting 0)

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
