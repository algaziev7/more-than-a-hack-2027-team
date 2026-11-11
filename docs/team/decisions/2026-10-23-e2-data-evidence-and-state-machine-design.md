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

### Amendment — the first version of this fix was itself broken (two independent findings, both verified)

A later review (another session, not Isken/Almaz) caught two real problems with the fix as first
written, before either was merged further:

1. **The fix was a no-op for the actual target scenario.** `restart_evidence_threshold` defaulted
   to `0.5` — exactly `tagging.TaggingConfig.restart_strength`'s default. A bare Smart Tagging
   `SET PIECES` window sets `restart_evidence` to that value for its *entire* span, including
   every frame `dead_ball.py`'s `tagged_stop` also confirms as dead. So on a real tagged
   stoppage — a throw-in, the exact case Almaz reported — `is_dead` latches `dead_confirmed` and
   `exit_dead_ok` clears it again *on the same frame*, every frame, and the latch never holds.
   Reproduced independently with the review's own repro before trusting it (confirmed dead on
   frames 5-20, a flat 0.5 restart hint across the whole sequence, strong team evidence from
   frame 25 — flips to `H` at frame 39 on the unpatched fix). Fixed: `restart_evidence_threshold`
   raised to `0.6` — strictly above tagging's bare hint, at or below E3's confirmed-restart pulse
   of `0.75` — plus a check in `decode()` that validates this against the real `tagging` config
   section when one is supplied, so the two thresholds can't silently drift back into collision.
2. **The latch has no expiry, and E3's own escape path can close.** `dead_ball.py` resets its
   `last_stop` context the moment the ball becomes unusable (occluded) — and the ball is missing
   on 41% of graded frames, in clusters. Without a recent stop, E3 only confirms live motion via
   `control` (strong, reliable team evidence) — so a stop followed by an occluded restart, with
   tracking still ambiguous once the ball reappears, could leave the latch set, and every
   subsequent H/A frame suppressed, for an unbounded stretch. Left open at first, deliberately —
   a third review then demonstrated it rather than just theorizing it (below), which changed the
   calculus from "needs real data to size a bound" to "needs *a* bound, size is secondary."

### Second amendment — a third review demonstrated the unbounded latch is a real failure, not just a risk

A third review (another session, independent of the second) gave a concrete repro rather than a
theoretical concern: confirmed stop on frames 50-80, then 920 frames (~37s) of neutral dead
evidence with strong, reliable team evidence the whole time — labels stayed `D` for all 920
frames, with *zero* chance of ever leaving, no matter how long the sequence ran. Reproduced
independently before trusting it. That changed this from "revisit once real data exists" to
"this needs a bound regardless of the exact real-world rate," since an unconditionally unbounded
freeze is a severe failure mode on its own terms, not something only real-data tuning can reveal.

**Fix: a safety valve, not a guessed expiry.** Sustained, reliable team evidence can still exit a
latched `D`, but only after `latched_team_dwell_s` (3.0s / ~75 frames by default) — several times
`team_dwell_s`, deliberately, so that length itself is what makes "team evidence won" categorically
different from the brief proximity Decision 6 exists to ignore, rather than a backdoor around it.
This reuses Decision 3's existing pause-not-reset dwell machinery; it's the same mechanism with a
different, longer threshold while `dead_confirmed` is latched, not new machinery.

**Two more bugs, both self-found while implementing that valve, both fixed before anything was
shared:**
- *Banking exploit.* The first implementation let team-candidate progress accumulated while
  gated (toward the long threshold) carry over once the gate lifted, suddenly counting toward the
  now-much-shorter `team_dwell_frames` — so a long run of mere proximity could cash in instantly
  the moment a single frame of real proof arrived, undercutting the whole point of requiring that
  proof. Fixed: that progress is discarded the moment `exit_dead_ok` actually clears the latch.
- *Wrong scope.* The fix for the above, as first written, discarded *any* pending candidate on
  that same frame — including an unrelated pending `D`-confirmation that happened to be in
  progress, which has nothing to do with the team-evidence gate. Fixed: only a pending `H`/`A`
  candidate is discarded; a pending `D` candidate is untouched.

Also fixed in the same pass, lower severity but real: the `tagging.restart_strength` cross-check
(finding 1's fix) read the raw config dict with a bare `.get()`, raising the wrong exception type
on malformed input and duplicating `TaggingConfig`'s own default instead of asking it. Switched to
`_section(config, "tagging", TaggingConfig)`, the same helper every other config lookup in this
module already uses.

### Third amendment — the "wrong scope" fix from the second amendment was still too broad

A fourth review found that the `pending_state in (H, A)` guard added above wasn't quite right
either: `dead_confirmed` can latch True even while `current_state` is already `H`/`A` — a single
`is_dead` frame sets it unconditionally (Decision 5's reasoning: it already carries E3's own
confirmed opinion), regardless of what `current_state` happens to be at that moment. If that
stray latch then gets cleared later by a genuine `exit_dead_ok` frame that lands in the middle of
an ordinary, never-gated turnover, the guard as written still discarded that turnover's progress
— delaying a completely unrelated H→A change by however many frames it had already accumulated.
Reproduced independently before trusting it: establish `H`; one `is_dead` frame that never
reaches `dead_dwell_frames` (so `current_state` stays `H`); then a genuine, sustained turnover to
`A` with one `exit_dead_ok` frame inside it — the turnover landed 9 frames late.

Fixed with two changes: the discard only fires when `current_state == D` at that moment (the
candidate was actually subject to the gate, not merely latched-but-irrelevant); and
`dead_confirmed` is now explicitly cleared the moment a transition actually leaves `D` for `H`/`A`
(whether via real proof or the safety valve), so a stale latch from a *previous* `D` period can't
resurface and interfere with a *later*, unrelated turnover either. Both paths now have dedicated
regression tests.

### Fourth amendment — the safety valve itself counted scattered observations, not sustained ones

A fifth review found that the safety valve (second amendment) reused Decision 3's pause-don't-
reset counter unmodified — and Decision 3's unbounded gap tolerance, exactly right for ordinary
dwell, is wrong here: it let 75 *scattered* supporting frames, spread over any length of time,
count the same as 75 consecutive ones. The stated justification for the valve (several seconds of
genuinely *sustained* evidence, categorically different from brief proximity) was never actually
enforced by the code. Reproduced independently with the reviewer's own repro before trusting it:
confirmed stop, then one supporting frame every 12 frames for ~37s — reached `A` at frame 918,
having never once seen anything resembling sustained support.

**First attempt, verified not to work before landing on the real fix:** reset the count when the
gap since the last supporting frame exceeds a bound (`team_dwell_frames`). This doesn't fix it —
any *fixed per-gap* bound still permits an arbitrarily long chain of just-under-the-bound gaps to
span an unbounded total duration; the reviewer's own 12-frame spacing sits under a 15-frame bound
by construction, so that fix left their repro unchanged. Checked by rerunning it before writing
anything further.

**Actual fix: a genuine sliding window.** `pending_count` (an integer) is replaced by
`pending_frames`, a deque of the frame indices supporting the current candidate. While gated, it's
trimmed to the last `2 * latched_team_dwell_frames` frames before its length is compared against
`latched_team_dwell_frames` — so the count can never reflect more than that many frames of real
elapsed time, however the supporting frames are distributed within it. Ordinary (non-latched)
dwell is untouched: the deque is left untrimmed there, preserving Decision 3's original unbounded
gap tolerance exactly. Dedicated regression test added for the sparse case.

On the real match (still placeholder tracking features): `D` share rose slightly, 7,514 -> 7,970
frames — not from team-evidence proximity, which has zero reliability in the placeholder, but
from Smart Tagging's real `tag_team_evidence`, which can itself be sparse across a long stretch
and was previously enough to trip the valve without being sustained either.

### Fifth amendment — confirmed live play cancels a pending stop; all evidence now ages out (2026-11-10)

Almaz's review of `96663a8` found two more, both reproduced on synthetic inputs before changing
anything:

1. **Live play didn't cancel a pending stop.** `H*30 + D + R*25 + D + .*50` switched H -> D at
   frame 56: two isolated stop frames combined across 25 frames of confirmed live play. Fix: an
   `exit_dead_ok` frame (that isn't itself dead) discards a pending `D` candidate. The current
   H/A label is kept; no new possessor is guessed. Without live play between them (`.` instead of
   `R`), two stop frames still combine, per Decision 3.
2. **Ordinary pending evidence never expired.** `H*30 + A*14 + .*1000 + A` switched H -> A at
   frame 1044 using support from 40s earlier. Fix: the fourth amendment's sliding window now
   applies to every candidate, sized by the new `evidence_window_s` (6s, 150 frames at 25fps);
   the latched case keeps its `2 * latched_team_dwell_frames` window. This partly reverses
   Decision 3's *unbounded* gap tolerance: gaps are still paused, not reset, but only within the
   window. The 100-frame-gap timing case is unchanged. 6s is a judgement call: long enough for
   the 100-frame synthetic occlusion, short enough to exclude 40s-old support. Revisit with real
   occlusion-length data.

Beks's PR #6 review found the same live-play bug independently (item 1 covers it). It also found
that `live_confirmed_threshold >= dead_threshold` was accepted: one reliable stop clue then set and
cleared the latch on the same frame, and proximity alone exited a confirmed stop (H at frame 54 in
`H*30 + D*10 + H*20` with the threshold at 0.9). Config validation now requires
`live_confirmed_threshold < dead_threshold`.

Still open (policy, not a bug): confirmed live play with no reliable team stays `D`, which
conflicts with `D` meaning stopped play. Needs a team decision.

## Decision 7 — tracking-first fusion: tags fill gaps, they are never averaged in (2026-11-11)

The first real-features run (aggregate coverage counts only, run locally) suggested Smart Tagging
was overruling tracking. Tag team evidence is full certainty for one team at a flat 0.5
reliability across whole attacking-phase windows, on about half of graded frames. Under the old
reliability-weighted average, tracking at 0.4 reliability saying `A` inside an `H` tag window
fused to a decisive `H`. A frame supporting the current state resets a pending turnover, so a
real turnover inside a stale phase window was actively cancelled. That fits the too-long
possessions in the same run. It is a mechanism that fits the counts, not a measured cause.

At the same time Beks (E4) found his reliability multiplied in the H/A margin that this decoder
also thresholds, counting it twice. He proposes dropping it from reliability (his branch
`e4/reliability-v1`). That makes contested tracking high-reliability with evidence near 0.5,
which in an average would also dilute tags exactly where they should help.

**Rule:** one source decides each frame.

| Tracking on this frame | Frame's team candidate |
|---|---|
| reliability >= `team_reliability_min`, margin decisive | tracking's team |
| reliability >= floor, margin not decisive (contested) | none: a pending count pauses |
| reliability below floor | the tag's team, if the tag clears the same floor and margin |

Why contested tracking pauses rather than letting the tag fill: a duel is real information that
nobody clearly has the ball, and phase tags almost always name the incumbent, so filling it
would cancel turnovers as they start. Pausing keeps a turnover's accumulated support (Decision 3).

Side effect: two sub-floor sources (e.g. 0.2 + 0.1) no longer add up to a decision, since one
source must clear the floor on its own. With Beks's current formula the contested case cannot occur:
his reliability includes the margin, so any frame at or above the 0.25 floor also has margin
>= 0.25 > 0.15. Duels all fall below the floor and tags still fill them; `team_sources["contested"]`
stays 0 until his change lands. The pause rule needs both.

Config coupling, added on review: each source must clear the floor alone, and every tag frame
carries `tagging.team_reliability`, so `decode()` rejects a non-zero tag weight below
`team_reliability_min` (as it already does for `dead_ball.evidence_weight`).

Not done yet, measure first: tag-only frames can still reset a tracking-based pending turnover
during an occlusion. If the comparison run shows that, restrict tag-only frames to supporting,
never resetting. Selection between variants uses synthetic cases and coverage counts, not labels
or the public window.

## Decision 8 — 1 s team dwell for controlled possession, with backdated boundaries (2026-11-11)

**Evidence.** A local four-way run (aggregate counts only) of main, E4 #14, this branch's Decision
7 and both together showed both changes add possessions (147 -> 383 combined), most of them short
(108 under 2 s combined). A bounce-back count added to the local smoke script showed 98 of those
108 snap back to the team that had the ball before, and only 7 of 84 with tracking support were
won on a near-tie margin (< 0.30). So they are brief, clear opposing touches or approaches, not
close duels; Decision 7's contested pause already handles duels.

**Rule, from the definition, not from the counts.** CHALLENGE.md: a change of possession needs
*controlled* possession ("a player keeps the ball for a few seconds"); "a simple touch of the ball
without control", "a deflection of a pass that does not intercept it" and "an aerial duel won
without subsequent control" do not count. 0.6 s of support is less than that, so `team_dwell_s`
becomes 1.0 s (25 frames at 25 fps). Fewer short spells afterwards is not evidence for the value:
a longer dwell removes them by construction.

**Backdating.** A longer dwell is also a longer delay (EVALUATION.md: 1 s late costs about a third
of spellF1). The definition puts the boundary at "the moment possession passes", i.e. the first
frame of the new team's control, not the moment we become confident. So when a change is
confirmed, the frames from its first supporting frame up to confirmation are relabelled. Only
paused frames or support for that candidate can lie in between (any other candidate restarts the
count), so nothing else is overwritten. Not applied to the Decision 6 safety valve: team evidence
alone ending a confirmed stop is too weak to move the stop's end earlier. Not applied to `D`
either (found on review): its 2-frame dwell costs about one frame, while backdating could relabel
up to `evidence_window_s` of unobserved play as a stoppage between two stray dead frames. Each transition now
records `frame` (the boundary) and `confirmed_frame`.

**Effect on the synthetic timing table** (`python -m tests.e2_scenarios`): boundary errors fall
for team changes from +14 / +15 frames to 0; stops stay +1 (their own dwell), restarts stay +1 (the frame carrying the restart proof has no team);
a 24-frame possession is now missed where a 14-frame one was. Isken's independent reference model
backdates too and still agrees on all 5,461 exhaustive and 200 seeded sequences. Local real-match
rerun (aggregate counts, no labels, no score) in `owners/belek_isken.md`: 251 possessions
against 383 for Decision 7 alone and 186 on `main`. Fewer short spells there are expected by
construction, not evidence for the value.

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
