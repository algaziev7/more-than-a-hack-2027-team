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

## Dependency risk, raised for E3/Almaz — now resolved

Our `D` calls are only as good as how much real dead-ball evidence E3 surfaces. Smart Tagging's
`SET PIECES` code covers only 59 instances for a whole match's worth of stoppages. Resolved by
`almaz/dead-ball-priors` (merged to `main`): `possession/dead_ball.py` adds a motion-based signal
(sustained low ball speed + a tag window or an outside-pitch position) on top of tagging, so
`dead_reliability` is not limited to the 59 tagged instances. Still conservative by design (see
`docs/team/DEAD_BALL.md`) — a stationary ball mid-pitch with no supporting tag still gets no
opinion — but the dependency this decision flagged is real and is being worked, not silent.

## Decision 5 — `dead_dwell_s` shortened once E3's own confirmation delay was known

`docs/team/DEAD_BALL.md` and the updated `INTERFACES.md` state explicitly: *"Confirmation already
adds a delay, so E2 should account for it before adding further persistence."* Almaz's
`dead_ball.build_priors` already requires ~0.6s of sustained stillness (plus a supporting tag or
an outside-pitch position) before it confirms a stop at all. Decision 4's original
`dead_dwell_s = 0.32` (8 frames) would have stacked a second long wait on top of that for no
benefit — exactly the mistake the docs are warning against. Shortened to `0.08s` (2 frames),
kept only as a small margin against a single noisy frame of E3's signal, not as a second
confirmation window. (`team_dwell_s` is untouched — tagging's team hints carry no such built-in
confirmation delay, so our own dwell is still the only thing protecting the team decision.)

## Integration findings once E1/E3's real modules landed on `main`

Before any of this code existed independently, `main` gained real `possession/contracts.py`
(Azamat), `possession/dead_ball.py` + `possession/tagging.py` (Almaz), with 97 passing tests.
Rebasing onto that surfaced two real compatibility issues, both fixed:

- **`Prediction` shape.** The real shared `possession.contracts.Prediction` is `labels` +
  `diagnostics: dict`. An earlier draft of `decode()` returned a locally-defined `Prediction`
  with a `transitions: List[Transition]` field instead — incompatible with what anything
  downstream (Goblin's pipeline, a shared test) would expect. Fixed: `decode()` now imports and
  returns the real `possession.contracts.Prediction`, with the transition log under
  `diagnostics["transitions"]`.
- **Config convention.** `dead_ball.DeadBallConfig` and `tagging.TaggingConfig` both take the
  *whole* shared pipeline config dict and read only their own named section (e.g.
  `config["dead_ball"]`). `decode()` originally took a `StateMachineConfig` instance directly,
  which would have forced Goblin's pipeline to special-case this one stage. Fixed:
  `decode(match, features, priors, config)` now reads `config["state_machine"]` the same way,
  via a local `_section` helper mirroring `dead_ball._section`.

Verified end to end against the real match (`possession.data.load_match` ->
`possession.dead_ball.build_priors` -> `possession.state_machine.decode`, with a neutral
placeholder in place of Beks's not-yet-built `features.py`): runs in ~15s total on all 199,319
frames, produces a submission that passes `validate_submission.py`, and the `X` count matches the
documented ungraded-frame count exactly. Scored against the public window purely as a plumbing
check (never as a result): `spellF1` 0.0952 — far below the baseline, as expected, since without
real tracking-based team evidence the only team signal available is Smart Tagging's sparse hints.
This number is not informative about the real approach and should not be read as one.

## Decision 6 — exiting a confirmed stop requires proof play resumed, not just quiet

Found by Almaz, reviewing PR #6/#7 (2026-11-09): the throw-in scenario. Play is confirmed stopped.
The stop signal then simply goes quiet — the tag window ends, or E3 just has no opinion either
way — which is *not* the same as confirmed live. Meanwhile a player is standing near the ball,
waiting to take the throw. Before this decision, `team_reliable` was only masked by `~is_dead`,
checked on the *current frame alone* — so the instant the dead signal stopped being actively
confirmed, team proximity was free to act, with nothing requiring positive evidence the throw had
actually been taken. Reproduced independently before trusting the report: a confirmed 30-frame
stop followed by 30 frames of neutral dead-signal + strong, reliable team evidence switched the
label to `H` 14 frames later, with zero evidence play had resumed.

Fix: once a stop is genuinely confirmed, a sticky `dead_confirmed` flag latches on — set by a
single `is_dead` frame (deliberately not gated by `dead_dwell_frames`; see why below), cleared by
a single frame of positive proof (`priors.restart_evidence` clearing `restart_evidence_threshold`,
or E3's own confirmed-live reading, `dead_evidence` reliably at or below `live_confirmed_threshold`).
While that flag is set and the current state is `D`, a team candidate (H/A) is treated as "no
decisive signal" — paused via the existing Decision 3 mechanism, not reset — rather than allowed
to accumulate toward a transition. This never affects the half-start default `D` (nothing has ever
confirmed a stop there), so an ordinary kickoff is untouched; it only gates *leaving a stop that
was actually confirmed*.

**Why a single `is_dead` frame latches it, not a full `dead_dwell_frames` run:** a single frame of
`priors.dead_evidence`/`dead_reliability` already represents E3's *own* confirmed output, which has
already paid its own confirmation delay (Decision 5's whole point). Requiring our own dwell on top
before trusting it would be exactly the double-confirmation Decision 5 already rejected.

**Cost of getting this right turned out to be real, not just conceptual.** Isken's exhaustive
5,461-sequence and 200-seeded-case differential tests (`tests/test_state_machine_validation.py`)
had to be updated, and the first two attempts at updating their oracle (`grouped_reference`) were
themselves wrong — the interaction between this latch and the existing pending-occurrence counter
(a `D` observation can latch the flag without itself transitioning state; an `R` between two
otherwise-qualifying `H` observations doesn't break their run but does unlatch mid-run) isn't
expressible as a purely declarative "group runs, check each run's own length" oracle. The oracle
is now a sequential walk, independently re-derived from the written policy rather than calling
`decode()` — less structurally different from production than the original design, but correct,
which matters more. Two existing scenario fixtures (`e2_scenarios.TIMING_CASES`'s "Restart" and
"Same-team restart", and `tests/test_state_machine.py`'s same-team-restart test) had implicitly
relied on team evidence alone ending a stop — exactly the bug being fixed — and needed a believable
restart-confirmation frame added to remain meaningful tests rather than silently pinning the old
behavior.

**Trade-off, stated plainly:** this makes `D`'s exit more dependent on E3's restart/live signal
actually firing. An untagged, untracked stoppage where the motion detector also misses the restart
could now stay `D` longer than reality. Judged to be the safer failure mode — a coach would rather
see "still dead" too long than a phantom possession — but it is a real cost, not a free fix.

## Explicitly deferred (not forgotten, not yet needed)

- No vectorization of the per-frame loop — 199k frames is cheap in plain Python; confirmed at
  0.03-0.04s against both synthetic and real-scale inputs.
- No learned/HMM model — see Decision 2.
- No mid-possession confidence-based abstention beyond the `half == 0` case — a plausible v2.
- No `isinstance`/type-checking of `match`/`features`/`priors` against the real contracts (unlike
  `dead_ball._validate_inputs`) — this module stays duck-typed on purpose so the lightweight
  `SimpleNamespace` fixtures in `tests/test_state_machine.py` keep working unchanged; the real
  contracts' own constructors already validate on construction, so a second check here would be
  redundant for real callers and would break the synthetic ones for no benefit.
