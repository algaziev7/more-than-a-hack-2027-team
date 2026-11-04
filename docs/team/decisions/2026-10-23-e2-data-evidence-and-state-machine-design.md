# Decision: how raw data becomes evidence, and how E2's state machine decides

- Owner: E2 (belekayazbekov)
- Review: E4 (per TEAM_PLAN.md's reviewer table)
- Status: design agreed, not yet implemented
- Scope: this is reasoning and context, not a spec. The authoritative module contract is
  `docs/team/INTERFACES.md`; the authoritative task/data/scoring definitions are
  `CHALLENGE.md`, `DATA.md`, `EVALUATION.md`. If anything here conflicts with those, they win.

## The task, compressed

For every one of 199,319 tactical-video frames, output `H`/`A`/`D`/`X`. Ranked on `spellF1`
(possessions matched by temporal IoU across thresholds 0.3-0.7); `macroF1` is the tie-break.
Published floor: `spellF1` 0.2433. Full detail: `CHALLENGE.md`, `EVALUATION.md`.

## What the raw files actually contain, and what we pull from each

**ATD (`*_atd.xml` + `*_atd.txt`)** — one line per video frame:
`frame_id : player1;player2;...;player46 : ball`, each group `x,y,speed`, normalised 0-1,
`N`/`NaN` for a missing observation. The XML assigns each of the 46 track slots to a team (no
player identity, no persistence across the match). `frame_id` is 1-based; `video_frame =
frame_id - 1`. Verified against the real file: alignment agrees, teams resolve to Barcelona (H)
/ Atletic Club (A), ball visible on 56.9% of frames — matches DATA.md exactly.

What we pull: ball position per frame, every tracked player's position and team, per frame.
Nothing else — no identity, no history across slots.

**Smart Tagging (`*_smart_tagging.xml`)** — 638 intervals, each `{code, start_s, end_s, tags}`.
Time is seconds from video frame 0, so `round(seconds * 25)` is a video frame (verified: both
real kickoffs fall inside their tagged "Kick Off (Start)" window). `Team` tag is `Barcelona` /
`Atletic Club` / `N/A` (36 instances, including every throw-in).

What we pull: candidate restart/stoppage windows (`SET PIECES` code) and a second, independent
opinion on which team a phase favours — treated as a vote, not a fact, since it's automatic and
unreviewed (DATA.md is explicit about this).

**Homography** — not used for this decision. It maps pitch coordinates to video pixels; useful
for visualising/debugging on the broadcast feed, not for deciding who has the ball.

## Decision 1 — evidence is a (value, reliability) pair, not a hard per-frame guess

The baseline (`starter/baseline.py`) makes a hard winner-take-all call every frame (nearest
single player, ball missing -> no vote) and only fixes the resulting flicker with a symmetric
smoothing window afterwards.

We decided the upstream modules (E4's features, E3's priors) should hand E2 **soft evidence with
an explicit reliability**, per `docs/team/INTERFACES.md`:

- `features.team_evidence` / `team_reliability` — e.g. compare nearest-Home-player distance vs.
  nearest-Away-player distance and turn the *gap* into a soft score, rather than "closest player
  wins." A near-tie should carry low confidence, not a coin-flip winner.
- `priors.dead_evidence` / `dead_reliability` and `priors.restart_evidence` — from ball motion
  (near-zero speed, long missing stretches) and `SET PIECES` tag overlap.
- `priors.tag_team_evidence` / `tag_team_reliability` — from the Smart Tagging `Team` tag, with
  `N/A` mapped to zero reliability rather than guessed.

Why: it lets the state machine (Decision 2) tell "no evidence" apart from "evidence that's
genuinely contested" instead of both collapsing into the same hard guess, which is what causes
the baseline's flicker in the first place.

## Decision 2 — E2's decode() is a dwell-based hysteresis state machine, not a smoother

- One `current_state` in `{H, A, D}` (not `X`). A per-frame candidate state is computed from the
  fused evidence; the state only switches once a candidate has been the single best-supported one
  for **N consecutive frames** (the dwell). Weak/absent evidence casts no vote and the output just
  repeats the current state — this is what makes "missing ball does not imply D" and "do not
  invent confident team changes" mechanical rather than aspirational.
- Dead and team transitions get **separate dwell lengths** (dead shorter, team longer) — a
  stoppage is often announced cleanly by reliable tagging evidence; a turnover should need more
  sustained proof than a single touch.
- **Every half starts in `D`**, never "carried over" or "unknown." This is *correct* for the
  second half, which is graded from frame 110,808 but doesn't kick off until 113,742 (FAQ.md) —
  ~2,934 genuinely dead graded frames at the start of the half. It is only *harmless*, not
  correct, for the first half, which is graded from the kickoff itself and so is live from frame
  one (DATA.md) — `D` there is wrong for about one dwell window's worth of frames until evidence
  pulls it to the real state, the same latency cost paid at every other transition (see the dwell
  trade-off below). Worth stating plainly: the uniform default is a deliberate simplification that
  avoids special-casing "is this the start of a half," not a claim that it's the right label in
  both cases. Starting "unknown" and abstaining (`X`) would still be a trap either way: `spellF1`
  back-fills a leading run of `X` with the half's *first real decision*, which for the second half
  would be the eventual kickoff team — exactly the wrong label for a dead stretch.
- `X` is reserved for genuinely ungraded frames (`half == 0`). Every graded frame gets a concrete
  call, so spell boundaries stay well-defined.
- Deterministic and rule-based for v1, on purpose — `TEAM_PLAN.md` says start here; an HMM/learned
  model is an explicit, optional, later step, not a v1 requirement. There is also no legitimate
  training signal for one yet (only 5 minutes of real labels, reserved for pipeline checks).

## Decision 3 — a "no decisive signal" frame pauses the dwell count, it does not reset it

Found on review, before any code was written: an earlier version of this design reset the dwell
counter on *any* frame that wasn't a clean match to the pending candidate, including a frame with
no decisive signal at all (ball not visible, nothing reliable). That's a real problem given the
ball is missing on 41% of graded frames, and in clusters (an occlusion lasts many consecutive
frames), not as isolated single frames. A genuine turnover overlapping a missing-ball burst could
have its dwell count reset every frame of that burst, pushing detection far later than the nominal
dwell length — or, if gaps recur often enough, never reaching it at all.

Fix: a frame with no decisive candidate leaves the pending count untouched (pause, not reset).
Only a frame that actively supports staying in the current state, or supports a *different*
competing candidate, resets progress toward the pending one. This needs its own synthetic test —
a sustained turnover with missing-evidence frames scattered through it — alongside the nine
already planned.

## Decision 4 — the dwell length is a real, quantified cost, not a free safety margin

`EVALUATION.md`'s own numbers: a transition called 8 frames late scores ~0.89 on that spell, 25
frames (1s) late scores ~0.65. The dwell length is exactly how late every genuine transition gets
called, by design. `team_dwell_s = 0.60` (15 frames) is a starting point, not a settled constant —
worth revisiting once Decision 3's fix is in, since a dwell that tolerates gaps may not need to be
as long to get the same flicker protection.

## Dependency risk, not an E2 decision — raised for E3/Almaz

Our `D` calls are only as good as how much real dead-ball evidence E3 surfaces. Smart Tagging's
`SET PIECES` code covers only 59 instances for a whole match's worth of stoppages; if
`dead_reliability` stays near zero outside those tagged windows, long untagged dead stretches get
silently absorbed into whichever team held the ball before. `TEAM_PLAN.md` already asks E3 for a
broader motion-based signal, not just tagging, so this may already be covered — worth confirming
rather than assuming.

## Explicitly deferred (not forgotten, not yet needed)

- No vectorization of the per-frame loop — 199k frames is cheap in plain Python; revisit only if
  it's measurably slow against real data.
- No learned/HMM model — see above.
- No mid-possession confidence-based abstention beyond the `half == 0` case — a plausible v2.
- No `possession/contracts.py` / `features.py` / `tagging.py` — those stay E1's / E4's / E3's;
  this module only reads the attribute names `INTERFACES.md` already promises (duck-typed), so it
  doesn't block on them existing.
