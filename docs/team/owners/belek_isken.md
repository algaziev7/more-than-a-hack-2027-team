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

Reviewed and merged PR #7 (Isken's hardening pass: real match.fps use, ceil-not-round dwell
rounding, cross-contract shape validation, config range checks, and 23 new tests including an
independently-authored exhaustive/seeded differential reference) after running it myself and
reproducing its core bug claim against the unpatched code first.

Fixed a bug Almaz found reviewing both PRs (Decision 6): team evidence alone could resume a
confirmed stop once the dead signal merely went quiet (not confirmed live) -- e.g. a player
standing near the ball waiting to take a throw-in, before the throw is taken. Reproduced
independently before trusting the report. Fix: a sticky `dead_confirmed` latch, cleared only by
positive restart/live-motion proof, gates leaving `D` (never affects the half-start default, so
an ordinary kickoff is unaffected). Required updating Isken's exhaustive-oracle tests too -- the
interaction between the latch and the existing pending-counter isn't expressible as a purely
declarative run-grouping oracle; it's now an independently-authored sequential walk instead. Full
writeup in the decision doc's Decision 6.

Verified end to end against the real match with E1's `load_match`/E3's `build_priors` (features
still a placeholder): runs in ~15s, `X` count still exact, `D` share increased (6,384 -> 10,883
frames) as expected -- the fix makes some previously-premature H/A calls correctly stay D longer.

Two further rounds of review on that same fix, both caught before reaching anyone else:

- A second review found the fix was a no-op for the actual target scenario: `restart_evidence_threshold`
  defaulted to exactly `tagging.restart_strength`'s default (0.5), so a bare SET PIECES tag
  window alone cleared the latch on the same frame it got set. Reproduced with the reviewer's own
  repro before trusting it; fixed by raising the threshold to 0.6 and validating it against the
  real tagging config at decode() time.
- A third review demonstrated (not just theorized) that the latch had no expiry at all -- 920
  frames (~37s) stuck in D in their repro, confirmed independently. Fixed with a safety valve:
  sustained team evidence can still exit a latched D after `latched_team_dwell_s` (~75 frames),
  several times longer than an ordinary change needs. Found and fixed two more bugs of my own
  while building that valve (a "banking exploit" letting gated progress cash in cheaply the
  instant the gate lifted, and an over-broad reset that also wiped unrelated pending D-progress)
  before either reached anyone. Full history in the decision doc's two amendments to Decision 6.

Real match, after three rounds: `D` share moved 6,384 -> 10,883 -> 63,518 -> 7,514 across the
fixes -- each swing explainable by the mechanism just fixed, not noise.

A fourth review then found the second amendment's own fix was still too broad: `dead_confirmed`
can latch True while `current_state` is already H/A (a stray `is_dead` frame that never reached
`dead_dwell_frames`), and clearing it later was wiping an ordinary, never-gated turnover's
progress -- delaying an unrelated H->A change by 9 frames in their repro. Reproduced
independently before trusting it. Fixed: the discard now requires `current_state == D` at that
moment (the candidate was actually subject to the gate), and `dead_confirmed` is explicitly
cleared the instant a transition leaves `D`, so a stale latch from a previous stop can't
resurface against a later, unrelated turnover either. Third amendment in the decision doc; this
one didn't move the real-match label counts (placeholder features have zero team reliability
everywhere, so the scenario this fixes can't occur without real tracking evidence yet).

A fifth review found the safety valve itself (second amendment) never actually required
*sustained* evidence, just "75 occurrences, however scattered" -- it reused Decision 3's
unbounded gap tolerance unmodified. Reproduced independently (scattered touches every 12 frames
for ~37s still eventually won). My first attempted fix (reset on a per-gap bound) was verified
*not* to work before I wrote anything further -- any fixed gap bound still lets enough
just-under-the-bound gaps chain into an arbitrarily long span. Real fix: replaced the plain
pending counter with a deque of supporting frame indices, trimmed to a genuine sliding window
(`2 * latched_team_dwell_frames`) while gated; ordinary dwell keeps its original unbounded
tolerance untouched. Fourth amendment in the decision doc. Real match: `D` share rose slightly,
7,514 -> 7,970 -- this time via Smart Tagging's real (if sparse) team hints, not team evidence,
since placeholder features still have zero reliability.

A sixth review (Almaz, on `96663a8`) found two more, both reproduced on synthetic inputs first:
confirmed live play didn't cancel a pending stop (two isolated `D` frames 25 live frames apart
made a stop), and ordinary pending evidence never expired (a touch 40s old completed a
turnover). Fixed: live play now discards a pending `D` candidate, and every candidate uses a
sliding evidence window (`evidence_window_s`, 6s). Fifth amendment in the decision doc. Beks's
PR review raised the same live-play bug, plus overlapping live/dead thresholds letting proximity
alone exit a stop; config now rejects `live_confirmed_threshold >= dead_threshold`. The
real-match smoke test was not re-run for this change.

### Next exact action

Still blocked on Beks/E4's real `features.py` for a meaningful accuracy picture -- everything
above is plumbing/policy correctness, not a result. Once that lands, re-run the full pipeline,
measure actual `D`-spell lengths, and reconsider `team_dwell_s`/`latched_team_dwell_s`/the other
Decision-6 thresholds with real tracking data in the loop, per the decision doc's own "revisit,
don't treat as fixed constants" framing.

### Handoff

- Changed files: `possession/state_machine.py`, `tests/test_state_machine.py`,
  `tests/e2_scenarios.py`, `tests/test_state_machine_validation.py`, the decision doc.
- Reference: PR #6 (merged PR #7 into it), plus six follow-up commits for Decision 6 and its
  five amendments, on `e2/state-v1` -- not yet merged to `main`.
- Verification: `python -m unittest discover -s tests` -- 144/144 pass (132 + 12 new for Decision
  6 and its amendments), Python 3.9 system interpreter. Real-match smoke test as above; not re-run
  after the fifth amendment.
- Untested: anything against real E4 features; only a neutral placeholder so far.
- Interface changes: `StateMachineConfig` gained `restart_evidence_threshold`,
  `live_confirmed_threshold`, `latched_team_dwell_s`, and `evidence_window_s` (all validated, all documented in
  Decision 6 and its amendments).
- Decision: team evidence must never be the sole proof a stop ended, except after a much longer
  wait than normal (the safety valve) so the latch can never freeze a half indefinitely; the
  latch only ever gates a candidate that was actually live while `current_state == D`, never a
  stray reading from an unrelated moment. Thresholds for "what counts as proof" are judgement
  calls, documented as such, not data-derived.
- Next task: wire in real features; revisit dwell/threshold defaults, including
  `latched_team_dwell_s`, once real `D`-spell-length data exists.
- Open policy question (Almaz): confirmed live play with no reliable team stays `D`. Needs a
  team decision.
- Help needed: E4 review of the fusion/threshold logic generally; Almaz/E3 on how often real
  dead-ball evidence will carry genuine restart/live-motion confirmation vs. staying neutral --
  directly informs whether `latched_team_dwell_s`'s current default is in the right range.

Update this file in the same commit as your code, then push your branch.
Branch progress is not integrated progress until its PR is merged.

