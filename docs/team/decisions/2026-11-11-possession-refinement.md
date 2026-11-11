# Proposed E2/E3 candidate: source-aware offline possession refinement

User requested implementation of live/unknown handling, tag-resistant pending
turnovers, boundary/short-possession handling, and enabled bounded ball gaps.
Proposal recorded before implementation; the implementation and evidence below
are now complete. E2/E3/E4 review is required before main.
The work is isolated on `e2/possession-refinement`, with PR #11 and #13 dependencies.
Shared MatchData/FeatureData/PriorData/Prediction fields and signatures stay unchanged.

The new versioned candidate config will enable E2 offline refinement and E3's
0.2 s bounded missing-ball tolerance. Existing configs retain causal timing; tracking-first fusion is inherited from
PR #13. The new config explicitly enables the offline policy.
E2 adds numeric limits for backdating, strong-tracking confirmation and restart
lookahead plus one Boolean `offline_refinement` switch. Diagnostics are additive.

- Internally distinguish live/unknown from stopped play. Output X until a team
  is established; use a nearby later confirmed team to assign the initial live
  interval retrospectively, bounded by time, half, stop evidence and conflicting
  team evidence. Never invent H/A when neither team has evidence. A completely
  unresolved interval remains X; the scorer's fill means this cannot guarantee
  removal of D in spell scoring. That information limit must remain explicit.
- Pending team evidence is bounded in age. A tag-only opposing candidate cannot
  erase pending tracking support; actual opposing tracking still can. Protection
  expires when supporting tracking ages out. Tags alone still work.
- Confirm sustained strong tracking faster than ordinary evidence, while keeping
  the long stop-latch safety dwell. A short deflection must not qualify. Retain
  ordinary hysteresis for weaker clues and tag-only evidence.
- After confirmation, place a boundary at the earliest supporting observation
  inside a fixed lookback, never across a half, prior confirmed transition, or
  stop/live barrier. Record confirmation time separately from final boundaries.

Candidate values are explicit engineering hypotheses, not tuned against match
labels/counts: 0.32 s strong consecutive control, reliability >=0.75 and team
margin >=0.7; up to 0.6 s boundary lookback and 2 s restart-team lookahead.
Synthetic positives AND adversarial negatives will determine implementation
correctness; they do not establish competition accuracy.

## Implemented result and use

`configs/possession-v2.json` enables the complete candidate. On an authorised
laptop, run:

```sh
python scripts/predict.py --config configs/possession-v2.json --output runs/dev/team-v2.csv
python scripts/check_solution.py runs/dev/team-v2.csv
```

`possession/refinement.py` implements the policy. `state_machine.decode` validates
settings and selects causal or refined execution. No shared fields/signatures
changed. PR #13's tag-weight check now tests whether tag evidence is actually
present, so disabled/missing tags can use a higher tracking reliability floor.
The active-tag regression remains, and disabled/absent cases are added.

Final `transitions` describe the exported boundaries. `confirmations` record
confirmation frames, assigned boundaries and reasons. `live_unknown_frames`
counts unresolved graded X frames; `protected_tracking_frames` counts tag-only
votes suppressed while fresh tracking supports a pending alternative.

Verification on Python 3.15.0 with the existing pinned environment:
- Full suite: **228 pass, no skips**.
- 23 new tests cover bounded restart-team assignment, unresolved live play,
  opposing evidence, long gaps, tag-only behavior, protection expiry, stop latch,
  strong/weak/brief possessions, FPS scaling, half/excluded-frame independence,
  deterministic output and team symmetry (60 seeded scenarios).
- A 199,319-frame invented match passes real feature/prior/decoder stages,
  deterministic export and exact-byte/official-validator manifest checks.
- The supplied strong 14-frame possession is retained with boundaries at frames
  30 and 44; the causal baseline omits it. Strong direct turnovers are assigned
  to their first supporting frame after eight consecutive observations at 25 fps.
- Weak 14-frame possessions and strong deflections shorter than eight frames
  remain filtered. Safety-valve exits remain at confirmation, without backdating.

The caller can inspect original causal behavior by setting
`state_machine.offline_refinement=false`; gap tolerance is independently configured.
Both paths use the inherited tracking-first source arbitration.

Limits: eight seconds of live evidence with no past/future team observation
cannot establish H/A. Such intervals are explicitly X and reported, and spellF1
can still carry the prior D through them. Nearby confirmed evidence resolves
only bounded intervals with no intervening stop/half/conflicting team evidence.
The candidate cannot infer events that tracking/tags never support. E3's own
stop-confirmation delay is not retrospectively removed. No real-match accuracy,
public-label tuning, full-data execution or second-laptop reproduction is claimed.

## Review checklist

Equivalent review against `.claude/agents/pre-commit-reviewer.md`: checked full
changed execution files, callers, shared contracts, source/config capture,
bounded evidence lifetime, half resets, stop precedence, causal fallback and
output diagnostics. Pending evidence uses a deque and constant-time tracking
counts; retrospective slices are bounded. Synthetic tests establish the stated
invariants. No blocking code finding remained after fixing the inactive-tag
validation regression. PR #14's separate feature/diagnostic findings are outside
this change and that PR is not included as a dependency.
