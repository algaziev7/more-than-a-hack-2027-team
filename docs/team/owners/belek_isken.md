# Belek and Isken — Possession state machine

- Owner: Belek and Isken
- Status: two independent tracks in progress, by agreement (compare and reconcile later)
- Branch: Belek on `e2/state-v1`; Isken on `e2/validation-plan`
- Reviewer: E4
- Owned files: possession/state_machine.py; state-machine configuration and tests
- Current milestone: first four focused hours
- Last update: 2026-10-25

## Pair coordination

Belek and Isken agreed to build independent solutions on separate branches and compare them
later, rather than merging work-in-progress into one track. This file records both tracks side
by side until that comparison happens; neither section overwrites the other.

## Isken's track (`e2/validation-plan`)

### Completed and verified

Prepared [E2_VALIDATION_PLAN.md](../E2_VALIDATION_PLAN.md), covering the
transition specification, synthetic/reference testing, metric semantics,
environment and local-data setup, eligible external validation, and exact
reproduction. The proposed pair split leaves E4 as the behavior/policy reviewer.

Checked the requested docs and official source. Confirmed expected tactical
tracking/tagging/homography filenames are present; the expected tactical video
filename is absent. Presence checks only: no restricted contents were opened.
Python 3.11 is available, but no project environment or team modules exist yet.
No implementation, algorithm tests, scorer execution or full-data runs completed.

### Next exact action

On each developer's task branch, agree the transition policy and smallest typed
synthetic fixture with E1/E3/E4, then implement the first pass/turnover/stoppage/
half-reset slice. Follow sessions 0–2 h and 2–5 h in the validation plan.

### Handoff

- Changed files: new validation plan and this E2 handoff; no executable code changed.
- Reference: base commit `22cb24b`; documentation on `e2/validation-plan`,
  awaiting review and not integrated progress.
- Verification: `git diff --check` passed. A standard-library documentation check
  resolved 31 local Markdown links and parsed all 5 shell blocks with `bash -n`;
  no errors. These are documentation checks, not algorithm tests.
- Untested: dependency installation, every proposed team command, asset integrity,
  prediction, runtime, external accuracy and cross-laptop reproduction.
- Interface changes: none implemented. E2/E3 must agree the missing-value policy
  for restart evidence; E1/E4/E5 review the proposed shared harness additions.
- Decision: synthetic correctness first, independent reference decoder, official
  metric reuse, other-match quality evaluation if eligible data is available.
- Next task: agree policy and build the smallest synthetic vertical slice.
- Help needed: E1 contracts and environment; E3 neutral/restart semantics; E4
  metric/behavior review and external-data feasibility; E5 integration/CI.

## Belek's track (`e2/state-v1`)

### Completed and verified

Implemented `possession/state_machine.py`: a dwell-based hysteresis state machine (not a
per-frame classifier smoothed afterwards). Design and the review that shaped it are in
[2026-10-23-e2-data-evidence-and-state-machine-design.md](../decisions/2026-10-23-e2-data-evidence-and-state-machine-design.md),
including a bug found and fixed before any code existed (Decision 3: a "no decisive evidence"
frame must pause the dwell count, not reset it, given the ball is missing on 41% of frames in
clusters). 10 synthetic tests pass (`python -m unittest tests.test_state_machine -v`); smoke-
tested at full match scale (199,319 frames, random realistic evidence) in 0.04s, with the `X`
count exactly matching the real ungraded-frame count from DATA.md.

### Next exact action

Wire real evidence in, now that E1's contracts/data.py and E3's dead_ball.py/tagging.py exist on
`main` -- confirm `INTERFACES.md`'s field names still match what `state_machine.py` duck-types
against (it predates the merged contracts), then run against the real match end to end.

### Handoff

- Changed files: `possession/state_machine.py`, `tests/test_state_machine.py`, the decision doc.
- Reference: commits `af30411`, `39c81da` on `e2/state-v1` (not yet merged to main).
- Verification: `python -m unittest tests.test_state_machine -v` -- 10/10 pass. Full-match-scale
  smoke test with synthetic random evidence -- 0.04s, correct X count.
- Untested: anything against real E1/E3/E4 outputs; only synthetic fixtures so far.
- Interface changes: none yet -- duck-typed against INTERFACES.md's promised field names rather
  than importing contracts.py, specifically so this didn't block on E1/E3/E4 existing.
- Decision: deterministic rule-based hysteresis for v1, not a learned model (no legitimate
  training signal exists yet); dwell length is a real, quantified latency cost, not free margin.
- Next task: validate against the now-merged real contracts/dead_ball/tagging modules.
- Help needed: E4 review of the fusion/threshold logic; confirmation from E3 on how broad the
  real dead-ball evidence coverage is (see the decision doc's dependency-risk note).

Update this file in the same commit as your code, then push your branch.
Branch progress is not integrated progress until its PR is merged.

