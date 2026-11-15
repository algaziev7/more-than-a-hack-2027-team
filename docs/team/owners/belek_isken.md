# Belek and Isken — Possession state machine

- Owner: Belek and Isken
- Status: Decisions 1-11 merged on main through PR #18
- Branch: `main` at `5e8619b` (historical work: `e2/half-start-gate`)
- Reviewer: E4
- Owned files: possession/state_machine.py; state-machine configuration and tests
- Current milestone: frozen-config verification and release sign-off
- Last update: 2026-11-14 documentation sync

## Current-main synchronization

The half-start gate and start-tag eligibility rule described below merged in
PR #18 together with E1's `period_start` metadata. This documentation sync
independently reproduced all 236 tests on Python 3.12.12 with the pinned
dependencies. Remaining E2 work is to sign off the frozen config,
review authorised local diagnostics, and document the live-but-unknown-team
limit. Earlier corrective and branch sections are retained as historical evidence.

## Historical pair coordination

Isken's first validation pass (PR #7) is merged into Belek's PR #6. The current
corrective follow-up is based on `9883b4d` from PR #6. E4 remains the behavior
reviewer. The earlier validation record and Belek's handoff are retained below.

## Isken's corrective follow-up (`e2/decoder-edge-fixes`)

Five new regression tests reproduced the four review findings plus the related
zero-weight dead-evidence case before changing production code. Fixes:

- A frame classified as dead after restart weighting cannot also clear the
  stop latch. Contradictory clues preserve D; a later unopposed restart still
  releases the latch. The conflicting test values are valid synthetic priors,
  not a claim about E3's current default output.
- `latched_team_dwell_s` must exceed ordinary team dwell and require strictly
  more observations at the actual match fps. Invalid combinations now fail
  explicitly, including unequal durations that round to the same frame count.
- Zero reliability never contributes team or dead evidence, even with zero
  configured reliability floors. Tied team evidence remains non-decisive.
- Fuse both H/A columns and compare their signed difference symmetrically.
  An eight-machine-epsilon roundoff allowance makes the margin threshold
  inclusive for both teams; it is numerical tolerance, not a tuned threshold.
  Tests cover tracking/tagging/both sources at, above, and below the boundary.

Verification on Python 3.14.0/macOS arm64 with `requirements-team.lock`:
`python -m unittest discover -s tests` passes **149 tests** on this branch and
**162 tests** in a temporary combined checkout with `main` at `d2db589` (E4).
All four original standalone review repros now pass. `pip check` and
`git diff --check` pass. No restricted data or public answer labels were used.

Shared fields/signature and numeric defaults are unchanged; invalid dwell
combinations now fail. Behavior changes are confined to conflicting stop/restart
clues, zero-weight/tied clues, and floating-point margin boundaries. E1/E3/E4/E5
should review these semantics. Python 3.12, full-match accuracy, and second-laptop
reproduction were not tested in this follow-up.

Next exact action: Belek and Beks/E4 review and merge this follow-up into PR #6,
then complete its review against the now-merged E4 features. E5 pipeline wiring
and the unknown-team restart policy remain separate work.

## Isken's first validation pass (`e2/isken-validation`, historical)

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

## Belek's current task: half-start gate (`e2/half-start-gate`)

Decision 10 in the decision doc. An `await_start` period stays D until E3 confirms play started;
proximity and tags alone never open it, and the stop safety valve cannot act before the period's
first possession. E1's `PERIOD_START` in `possession/data.py` declares half 1 `live_at_entry`
and half 2 `await_start` from FAQ.md (Azamat agreed to the field; documented in INTERFACES.md).
Test fixtures declare `live_at_entry` centrally, so existing tests keep their meaning; the gate
has its own tests (Decision 10 lists them) and the reference model mirrors it.

- Tests: 231 pass on Python 3.12.16 (16 new, incl. the await-start exhaustive comparison,
  which now reaches gate expiry). Mutation check: removing each of the seven gate rules makes at
  least one test fail. Pre-commit review found that E3 disabled by config pinned await halves in
  D; the gate is now skipped and reported in that case.
- Smoke run (local, counts kept local): the gate works, but E3's generic live signal opened half 2
  long before the published kickoff. Almaz's investigation (PR #19) found no usable dedicated
  kickoff signal yet, so Decision 11 was added on the same branch.
- Decision 11: no opening before the period's first `Kick Off (Start)` tag frame; no tag means no
  restriction. Reuses E3's `_kickoff_context` (copied unchanged from PR #19; whichever merges
  second keeps one copy). Almaz confirmed locally (yes/no) that the half-2 tag does not cover the
  early opening. Tests: 236 pass on Python 3.12.16 (5 new, incl. 5 tag cases end to end at 25/50 fps, plus the exhaustive comparison rerun
  with a tag); four mutations of the rule each fail a test.
- Almaz's review (E3, approves the policy): the tag search now stays inside the current
  contiguous block of the period, with a regression test. Smoke result unaffected (two
  contiguous halves).
- Next: Belek's local smoke run of the final branch (half 1 unchanged; half 2 first possession no
  earlier than before; counts kept local); then review by Almaz, Beks and Azamat (INTERFACES).

## Belek's last task: tracking-first fusion (PR #13, squash-merged)

Decision 7 in the decision doc. Tracking and tag team evidence are no longer averaged: reliable
tracking decides the frame alone (contested tracking gives no candidate), and tags fill only
frames where tracking is below `team_reliability_min`. `_combine` is removed. `decode()` now also
returns `diagnostics["team_sources"]`, graded-frame counts decided by tracking, by tags, or left
contested. Paired with Beks's option (c) on `e4/reliability-v1` (reliability without the margin
factor), agreed by message.

- Review (another AI session, code reading): added a check rejecting a non-zero
  `tagging.team_reliability` below `team_reliability_min`, which would silently disable tags;
  fixed an invalid test input (non-neutral evidence at zero reliability). `contested` is always 0
  with E4's current formula, which already includes the margin in reliability.
- Tests: four new synthetic tests (contested tracking pauses; decisive tracking turnover beats a
  stale tag; tags fill sub-floor frames; two sub-floor sources no longer combine). They failed
  on the averaging code first, plus one config-check test. 185/185 pass on Python 3.12.16 with `requirements-team.lock`.
- Unmeasured: effect on the real match. Next: run the local four-way comparison (current, Beks's
  (c) only, this branch only, both) with aggregate counts only, then decide whether tag-only
  frames should also stop resetting a tracking-based pending turnover.
- E3 impact: unaffected directly; Beks's (c) changes E3's control check (reliability >= 0.5),
  so Almaz should review that PR.

### Decision 8 on the same branch (2026-11-11)

Beks's four-way run and the new bounce-back count (aggregates, run locally) showed most added
short possessions are brief clear opposing touches that snap straight back, not close duels.
CHALLENGE.md requires controlled possession, so `team_dwell_s` is now 1.0 s, and confirmed changes
are backdated to their first supporting frame (not D, not the safety valve), so the longer dwell does
not delay boundaries. Merged `main` (E4 #14, tooling #15) first.

- Tests: Isken's reference model gained backdating and still agrees on all exhaustive and seeded
  sequences; two new tests (backdating spans paused frames only, respects window trimming, never
  backdates D; safety valve not backdated). Pre-commit review: an instrumented decoder checked the
  no-overwrite invariant on 3,000 random sequences (4,495 backdates, no violation).
  Timing-dependent tests now assert `confirmed_frame`; tests with 15-frame assumptions were
  re-derived for 25. Two E5 pipeline tests (`tests/test_pipeline.py`) updated for the new
  boundaries, flagged for Goblin/Azamat. 190/190 pass on Python 3.12.16.
- Beks's PR #13 review: (1) real-match counts removed from this file and the decision doc,
  older ones included; they remain in Git history (this branch and `main` via PR #6), so the
  RELEASE.md step-6 history audit must cover them before any public release. (2) Backdating now
  stops at a support gap longer than the dwell, so a stray touch cannot pull a boundary back
  across an occlusion; trade-off documented in Decision 8's amendment.
- Almaz's PR #13 review: the tag-weight check rejected valid tracking-only runs (tags disabled,
  raised `team_reliability_min`). It now applies only when tag evidence is actually supplied.
  191/191 pass.
- Decision 9 (same branch): ported #16's tag protection and restart look-ahead into the single
  loop after comparing #13 and #16 (own comparison plus an independent review, same verdict:
  #13 as basis). Isken's reference model gained the look-ahead and still agrees on all exhaustive
  and seeded sequences; four new tests (the review's regression case sits inside one of them).
  195/195 pass on Python 3.12.16, 215/215 merged with `main` (incl. E3 #11); CI green on Ubuntu
  and Windows.
- Real-match smoke test re-run locally after the ports (completion status only, counts kept
  local): `X` count exact; possession count between `main` and Decision 7 alone; tag protection
  fires. Some possessions under 1 s appear. A synthetic fuzz (not committed) reproduces short
  possessions only via the gap rule truncating a support run (tag protection confirms more
  sparse-support turnovers, which then hit it) or the pre-existing safety-valve exit, and found
  no port bug; the real-match cases are presumed to share these causes, not verified case by
  case. Open for Beks: when the gap rule truncates, should the latest run alone have to meet
  the dwell?
- Next: E5 sign-off on the two `tests/test_pipeline.py` changes and the stale
  `docs/team/TECHNICAL_DOCUMENT.md:68-78` (post-merge); Almaz to decide on closing #16; team decisions on
  the second-half start and on asking the organisers about brief touches.
- Open, outside this change: the second half is graded ~2,934 frames before its kickoff, and
  player proximity at the centre spot reads as possession there (already true before Decision 8,
  now from the half's first frame). Team decision needed: treat each half start like a
  confirmed stop?
- Measured locally with `.local/compare_variants.sh` (Python 3.12.16), at `0d637d2`, before the
  gap-rule amendment below (not rerun since; possession count unchanged by construction, short-
  spell durations and D totals may differ); counts kept local per
  AGENTS.md / RELEASE.md, completion status only here. Done: `main`, Decision 7 alone and
  Decision 8 all run end to end with the `X` count exact. Observations, not evidence for the 1 s
  value (which rests on CHALLENGE.md's definition, Decision 8): the drop in short spells and
  bounce-backs is expected by construction; the possession count sits between `main` and
  Decision 7 alone; evidence coverage is identical for both #13 variants, as expected. Not a
  score: no labels were used. Merging is a team decision.

## Belek's track (`e2/state-v1`, merged)

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
still a placeholder): runs end to end, `X` count still exact, and `D` moved in the expected
direction -- the fix makes some previously-premature H/A calls correctly stay D longer. Real-match
counts are kept local.

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

Locally, after three rounds, each change in the `D` share was explainable by the mechanism just
fixed, not noise (counts kept local).

A fourth review then found the second amendment's own fix was still too broad: `dead_confirmed`
can latch True while `current_state` is already H/A (a stray `is_dead` frame that never reached
`dead_dwell_frames`), and clearing it later was wiping an ordinary, never-gated turnover's
progress -- delaying an unrelated H->A change by 9 frames in their repro. Reproduced
independently before trusting it. Fixed: the discard now requires `current_state == D` at that
moment (the candidate was actually subject to the gate), and `dead_confirmed` is explicitly
cleared the instant a transition leaves `D`, so a stale latch from a previous stop can't
resurface against a later, unrelated turnover either. Third amendment in the decision doc; this
one didn't move the local real-match label counts (placeholder features have zero team reliability
everywhere, so the scenario this fixes can't occur without real tracking evidence yet).

A fifth review found the safety valve itself (second amendment) never actually required
*sustained* evidence, just "75 occurrences, however scattered" -- it reused Decision 3's
unbounded gap tolerance unmodified. Reproduced independently (scattered touches every 12 frames
for ~37s still eventually won). My first attempted fix (reset on a per-gap bound) was verified
*not* to work before I wrote anything further -- any fixed gap bound still lets enough
just-under-the-bound gaps chain into an arbitrarily long span. Real fix: replaced the plain
pending counter with a deque of supporting frame indices, trimmed to a genuine sliding window
(`2 * latched_team_dwell_frames`) while gated; ordinary dwell keeps its original unbounded
tolerance untouched. Fourth amendment in the decision doc. Locally, `D` rose slightly, this time via Smart Tagging's
real (if sparse) team hints, not team evidence, since placeholder features still have zero
reliability.

A sixth review (Almaz, on `96663a8`) found two more, both reproduced on synthetic inputs first:
confirmed live play didn't cancel a pending stop (two isolated `D` frames 25 live frames apart
made a stop), and ordinary pending evidence never expired (a touch 40s old completed a
turnover). Fixed: live play now discards a pending `D` candidate, and every candidate uses a
sliding evidence window (`evidence_window_s`, 6s). Fifth amendment in the decision doc. Beks's
PR review raised the same live-play bug, plus overlapping live/dead thresholds letting proximity
alone exit a stop; config now rejects `live_confirmed_threshold >= dead_threshold`.

A later review (another AI session, reading the code) found that `dead_ball.evidence_weight`
becomes `dead_reliability`, so a weight below the decoder's `dead_reliability_min` (0.3) silently
discards every stop. `decode()` now rejects that combination, as it already does for the tagging
restart hint; disabling E3 (`enabled: false` or weight 0) is still allowed.

Real match, re-run locally on Python 3.12.16 after both fixes (placeholder features): `X` count
still exact, `D` unchanged. Unchanged is plausible, not proof:
with zero team reliability, team evidence comes only from contiguous tagging windows, so neither
fix's scenario likely occurs on this input yet.

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
- Verification: `python -m unittest discover -s tests` -- 164/164 pass on Python 3.12.16 with
  `requirements-team.lock` (`pip check` clean), macOS arm64, after merging `main` (E4 features)
  and Isken's PR #12. Earlier heads: 144/144 also on Python 3.9.6. Real-match smoke test re-run locally after the fifth amendment
  (`.local/smoke_real.py`, uncommitted): `X` exact, `D` unchanged.
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

