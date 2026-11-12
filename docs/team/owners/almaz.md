# Almaz — Event tags and stoppages

- Owner: Almaz
- Status: PR #11 merged; dedicated kickoff signal implemented, E2/E4 review required
- Branch: `e3/kickoff-confirmation`, based on main `fd7e6a4`
- Reviewer: Beks and Belek/Isken; Azamat for shared types
- Files: `possession/dead_ball.py`, `tests/test_kickoff.py`, and related E3 docs
- Last update: 2026-11-12

## Dedicated kickoff confirmation for PR #18 (2026-11-12)

### Local diagnostic follow-up

- Added a settlement-detail breakdown after Almaz's qualitative local result
  indicated the settlement prerequisite was unmet. Diagnostic-only counts now
  separate observed/usable centre positions from stillness, and look for slow
  centre observations just before the tag using the existing restart-context
  duration, within the same half. That lookback never changes detector evidence.
  The CLI also writes a readable `runs/kickoff-summary.txt` with categories only.
  No private counts, positions or match frames are recorded in this handoff.
- Current verification: **27 kickoff tests and 242 full-suite tests pass** on
  Python 3.15.0. Two added tests cover all settlement-detail categories and
  ensure diagnostic lookback cannot open the detector or cross halves.
  The CLI test checks the readable summary. `git diff --check` passes.
  Equivalent pre-commit review found no blocking issue; this remains diagnostics
  only, with all behavioral settings unchanged.
- Next human step: rerun `scripts/diagnose_kickoff.py` locally, open
  `runs/kickoff-summary.txt`, and share only half 2's settlement-detail category.
  Diagnose the assumption before designing a general synthetic behavioral fix.

- Almaz reports the human-run exactly-one check returned **NO**. The hosted
  assistant has not inspected restricted inputs or reports. The signal is not
  ready for E2 activation based on the current evidence. No thresholds changed.
- Added `summarize_kickoff_diagnostics` using optional counters in the actual
  detector, and `scripts/diagnose_kickoff.py` for a human terminal. It saves
  per-period gate/reset counts and a qualitative earliest unmet stage to
  ignored `runs/kickoff-gates.json`, without printing match diagnostics.
  No frame IDs or coordinates are returned. Reports still stay local.
- Gates distinguish absent tag context, unusable observations, settlement,
  sustained motion, departure, control and contradictory stops. An unmet stage
  is a debugging lead, not an accuracy result or proven real-match explanation.
- Verification on Python 3.15.0: **25 kickoff tests; 240 full-suite tests pass**,
  no skips. Four new tests check stage classification, disabled/blocked cases,
  serialization/input invariance, and CLI output using mocked synthetic inputs
  in a temporary directory. No restricted command was run by the assistant.
  A separate 100-case seeded synthetic comparison against committed `7074c59`
  matched every PriorData field exactly. `git diff --check` and tabnanny pass.
- Equivalent pre-commit review checked the added CLI, detector counters,
  producer/consumer invariants and tests; no blocking finding identified.
- Next: Almaz runs the new command in a separate local terminal with the actual
  prediction config, opens the report locally, and shares only half 2's stage.
  Use the cause to design a general synthetic regression before any behavioral
  change. E1 interface sign-off and E2 integration remain pending.

### Belek's review corrections

- Addressed the two requested pre-merge changes from
  [Belek's review](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/19#issuecomment-6820670319).
  `_kickoff_context` now clips start/end to `[0, n)` and skips empty overlap.
  Added a regression reproduced failing before the fix for negative start,
  oversized end, fully excluded windows, empty windows and an empty timeline.
  A separate test preserves MatchData's existing rejection of unclipped events:
  this is helper hardening, not a relaxation of the public input contract.
- Documented bit 256's role as label-affecting E2 confirmation evidence and
  `None` flags as no confirmation in `docs/team/INTERFACES.md`, as requested by
  E2. E1/Azamat sign-off remains required; no consumer implementation changed.
- Verification: **21 kickoff tests pass; 236 full-suite tests pass**, no skips,
  on this session's Python 3.15.0 environment. `git diff --check` passes.
  Belek separately reports that the previous 234-test revision passed on
  Python 3.12 and merged with #18 without conflicts; that is reviewer-provided
  evidence, not a Python 3.12 run performed in this session.
- Repeated the equivalent pre-commit correctness/contract review on the full
  follow-up diff and its callers. No additional blocking finding identified.
- Review items 3/4 concern E2 policy and human-only local verification. No
  restricted-data check was run or claimed here. A generic fallback after a
  missing/expired tag can still accept pre-kickoff repositioning, so it would
  need an explicit change to the agreed half-start policy. Disabled E3 likewise
  remains an explicit E2 policy decision; no silent bypass was added to E3.
- Next: Belek re-reviews fixes 1/2, Azamat signs off on the interface note, and
  a human teammate checks locally whether half 2 emits exactly one kickoff
  confirmation, reporting only yes/no before E2 switches to the dedicated bit.

- Published implementation: `0a20640`; draft review PR:
  [#19](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/19).
- Implemented E3 option A on an isolated task worktree; shared main and other
  owners' worktrees are unchanged. `CONFIRMED_KICKOFF = 256` is an additive bit
  in existing `PriorData.diagnostic_flags`, proposed in DEAD_BALL.md before
  implementation. No shared dataclass/signature or E2 implementation changed.
- A `SET PIECES` / `Type=Kick Off (Start)` context must contain observed centre
  settlement, sustained departure, and bounded E4 control at kick/reception.
  One pulse per episode begins at confirmation, never at a tag boundary or a
  published match frame. Generic numeric priors and ordinary restart bits are
  unchanged, including their current missing-frame behavior.
- Kickoff-specific missing tolerance counts only observed support; both
  individual and repeated gaps are bounded by a cumulative pending budget.
  Reacquisition is checked against elapsed displacement, with/without raw speed.
  Long gaps, rejected samples, half changes, lost context and expiry reset it.
  A confirmed stop prevents a contradictory kickoff pulse.
- Added four explicit untuned settings: centre radius 1 m, departure displacement
  1.5 m, endpoint-control window 1 s, missing budget 0.2 s. Existing E3 dwell,
  speed, control cutoffs and restart context are reused. Values are engineering
  hypotheses, not chosen from the competition match or public labels.
- Added `event_counts.confirmed_kickoffs` to aggregate prior diagnostics and a
  human-terminal-only recipe in [DEAD_BALL.md](../DEAD_BALL.md) for investigating
  the generic opening signal, approach/departure, and start-tag coverage. The
  recipe writes restricted details to ignored runs/ and was syntax-checked only.
- Verification: Python 3.15.0, existing pinned temporary environment:
  `python -m unittest discover -s tests -q`: **234 pass**, no skips;
  19 new kickoff tests include both 25/50 fps, actual E4 geometry, stationary
  wait, centre approach, kick/reception control, exact gap timing, total-budget
  exhaustion, missing raw speed, missing tags/control/settlement, tag boundaries,
  half/reset/outlier cases, conflicting stop, disabled E3, numeric invariance,
  team-swap/mirror invariance, duplicate tags and validation.
  A gap-reset mutation fails the exact-confirmation regression as intended.
  `git diff --check`: pass. Documented Python recipes parse without execution.
- Equivalent pre-commit review used `.claude/agents/pre-commit-reviewer.md`:
  reviewed the complete E3 change, producer contracts and decoder consumer;
  fixed a possible contradictory stop/kickoff pulse and strengthened the gap
  test. No remaining E3 blocking finding identified. Owner integration review
  remains required; this is not approval of PR #18.
- No competition assets, extracts, public answer labels, local model outputs or
  restricted-data jobs were used. Real opening flags, ball trajectory and tag
  coverage remain unverified. Python 3.12 and real-match accuracy are unverified.
- **Exact next step:** Belek/Beks review the new signal semantics and defaults.
  Belek changes PR #18's awaiting-period opening/refresh to this bit, clears its
  latch and pending support on confirmation, bounds first-possession backdating,
  and resolves its disabled-E3 bypass against the agreed fail-closed policy.
  E5/E2 then run combined E4 -> E3 -> E2 synthetic tests for both period types
  at 25/50 fps. A human teammate runs the diagnostic recipe locally with the
  actual run config, keeps details local, and shares only conclusions. Do not
  claim the half-start issue fixed until the consumer change and local check.

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
