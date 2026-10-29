# Belek and Isken — Possession state machine

- Owner: Belek and Isken
- Status: validation plan drafted; implementation not started
- Branch: e2/validation-plan
- Reviewer: E4
- Owned files: possession/state_machine.py; state-machine configuration and tests
- Current milestone: first four focused hours
- Last update: 2026-10-25

## Completed and verified

Prepared [E2_VALIDATION_PLAN.md](../E2_VALIDATION_PLAN.md), covering the
transition specification, synthetic/reference testing, metric semantics,
environment and local-data setup, eligible external validation, and exact
reproduction. The proposed pair split leaves E4 as the behavior/policy reviewer.

Checked the requested docs and official source. Confirmed expected tactical
tracking/tagging/homography filenames are present; the expected tactical video
filename is absent. Presence checks only: no restricted contents were opened.
Python 3.11 is available, but no project environment or team modules exist yet.
No implementation, algorithm tests, scorer execution or full-data runs completed.

## Pair coordination

Belek and Isken share this role. Agree on separate tasks/branches and designate
one handoff editor per session to avoid conflicting edits to this file.

## Next exact action

On each developer's task branch, agree the transition policy and smallest typed
synthetic fixture with E1/E3/E4, then implement the first pass/turnover/stoppage/
half-reset slice. Follow sessions 0–2 h and 2–5 h in the validation plan.

## Blockers and dependencies

Shared contracts, environment lock, decoder and test harness remain proposed.
E1 must verify asset integrity and configure MTAH_DATA_DIR. Use synthetic inputs
while that proceeds. Role owners are assigned; collaborator access is not verified here.
No restricted data in this file or hosted AI context.

## Handoff

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

Update this file in the same commit as your code, then push your branch.
Branch progress is not integrated progress until its PR is merged.

