# Belek and Isken — Possession state machine

- Owner: Belek and Isken
- Status: Belek's decoder in PR #6; Isken's validation/fixes built on that PR, review pending
- Branch: Belek on `e2/state-v1`; Isken on `e2/isken-validation`
- Reviewer: E4
- Owned files: possession/state_machine.py; state-machine configuration and tests
- Current milestone: synthetic decoder validation and E3/export integration
- Last update: 2026-11-08 (Isken's track)

## Pair coordination

The earlier plan was two independent implementations. Isken's current task is
to validate and strengthen Belek's implemented decoder first. His follow-up is
based on `c8258b6` from PR #6; it does not replace Belek's branch. E4 remains the
behavior reviewer. Belek's historical handoff below is preserved; consult PR #6
for his later contract-integration changes and reported local smoke test.

## Isken's track (`e2/isken-validation`)

### Completed and verified

The earlier validation plan is merged via PR #3. This follow-up implements its
first synthetic validation increment; see the
[2026-11-08 report](../experiments/2026-11-08-e2-synthetic-validation.md).

- Added typed invented evidence fixtures, an independent offline run-group
  reference, exhaustive checks over 5,461 short sequences, 200 seeded half/gap
  cases, and 50 mixed-evidence team-swap checks.
- Added long-gap, pending-cancellation, unknown-team restart, short-possession,
  half-boundary, final-frame, deterministic-input, and timing tests.
- Reproduced and fixed match-fps handling, fractional-dwell rounding, timeline
  mismatch/broadcast acceptance, and out-of-range config values.
- Measured default direct-evidence delays: turnover/restart +14 frames, stop
  +1 frame at 25 fps. A 14-frame synthetic possession is missed entirely.
- Connected E3 priors to decoding/export on invented geometry; checked exact
  transitions, identical CSV bytes, and official format validation. Added
  official-metric usage checks on invented labels only.
- Full suite: **132 tests pass**, including **23 new tests**. Environment:
  isolated Python 3.14.0/macOS arm64 with the existing pinned dependencies.
  Dependency check and whitespace check pass. No restricted inputs were opened.

### Next exact action

Belek and Beks/E4 review the follow-up against PR #6. Decide whether pending
support should expire, how to represent live play with an unknown team, and
how short supported possessions should survive. Use the recorded timing cases
as the baseline for a bounded backdating experiment after policy agreement.
When E4 features exist, connect them to the synthetic integration slice.

### Handoff

- Reference: Belek's base `c8258b6`, PR #6; this increment is on
  `e2/isken-validation`, not integrated progress on main.
- Run: `python -m unittest discover -s tests` (132 pass);
  `python -m tests.e2_scenarios` reproduces the report's boundary table.
- Shared fields/signature: unchanged. `match.fps` now determines dwell counts;
  explicit conflicting config fps and mismatched evidence timelines fail.
  Non-integer dwell products round up. E1/E3/E4/E5 should review these semantics.
- Decision: retain current pause/default-D/restart policy and default thresholds;
  document counterexamples. Backdating is not enabled without a bounded policy.
- Untested: Python 3.12, real features/E5 pipeline, full-data local execution,
  external accuracy, scaling benchmarks, and second-laptop reproduction.
- Help needed: Belek/E4 behavior review, E3 unknown-team restart discussion,
  E4 feature builder, and E5 pipeline integration. Hidden-match improvement is
  not measured; the public answer window was not used.

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

