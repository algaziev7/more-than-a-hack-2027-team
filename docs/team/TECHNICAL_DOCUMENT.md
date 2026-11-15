# Possession system — technical draft

Status: integrated-main assembly draft, updated 2026-11-14 at `5e8619b`; not a
final submission document. E1-E5 implementations are merged. No final candidate,
team-named CSV, cross-laptop reproduction, or full-match accuracy result has
been established.

## Approach and assets

The intended system is deterministic: tactical tracking becomes geometric team
evidence, automatic tags and ball motion provide stopped/restart clues, and a
state machine produces H/A/D/X labels. Separating evidence from temporal decisions
makes missing observations and transitions explicit. The E5 pipeline calls each
owner's independent module and checks their frame-aligned contracts.

The loader reads tactical ATD metadata/tracking and optional automatic Smart
Tagging. Prediction does not require video, broadcast alignment, homography,
replacement tracking, a pretrained model or a GPU. These optional approaches
have not been evaluated by E5; their omission is not a quality result. Neither
prediction nor run-manifest validation reads ground truth.

## Canonical input and export — E1

Every ordered ATD frame ID is checked and converted from raw 1-based indexing to
the 0-based tactical axis. Positions become metres. Missing values remain NaN
with observation masks, including speed placeholders without ball coordinates.
Slots have known team membership without assuming stable player identity. Event
intervals preserve overlaps and original tags, with clipped half-open frame bounds.
The supplied half masks come from the organiser's published game constants.

Optional caches use content/config/schema/code hashes, numeric arrays and JSON
without pickle. Writes are atomic; corrupt entries are rebuilt. E1's CLI validates
JSON, seeds Python/NumPy, and keeps local paths outside versioned settings. Export
requires all 199,319 labels and writes deterministic UTF-8 CSV with LF newlines.
See [E1's method and limits](SETUP.md#e1-technical-document-section).

## Tracking evidence — E4

Features include nearest and next-nearest team distances, distance advantage,
nearby slot counts, boundary proximity, missing-ball duration and ball speed.
Each feature has a validity mask. Implausible ball/slot jumps are rejected and
speed disagreement reduces usability. Track-slot displacement checks quality;
it does not identify a player through time. Unknown geometry stays neutral.

An in-pitch ball within 3 m of a player from either team provides an H/A distance
clue. Reliability falls with distance and fast ball motion; whether opposing
distances are too similar is left to E2's margin check, so it is not counted twice. Cutoffs are untuned engineering heuristics, not fitted probabilities.
E4 does not smooth possessions. Exact units and reliability rules are in
[Beks's handoff](owners/beks.md).

## Tag and stoppage evidence — E3

Tag semantics distinguish attacking and defending phases. Conflicting hints
cancel, repeated tags do not strengthen evidence, and unknown/N/A teams remain
neutral. Set-piece intervals provide approximate restart context rather than an
exact restart instant. Tags are automatic clues correlated with tracking, not
independent ground truth.

Sustained slow ball observations support a stop only with set-piece or outside-
pitch context. A stationary or missing ball alone is insufficient. Sustained
credible in-pitch movement with stop/control context supports live play. A
confirmed stop can produce one stronger restart pulse. Missing/unusable
observations and half changes reset motion history. These rules are untuned;
see [DEAD_BALL.md](DEAD_BALL.md) for thresholds and reason flags.

## Possession rules — E2

`possession/state_machine.py` turns the per-frame evidence into labels with a
hysteresis state machine. The reasoning behind each rule is in the
[E2 decision record](decisions/2026-10-23-e2-data-evidence-and-state-machine-design.md)
(Decisions 1-11).

- **Team evidence.** Tracking whose reliability clears a floor decides a frame
  alone; contested tracking (a duel) gives no vote. Tags fill only frames where
  tracking is below the floor and are never averaged with it. A tag-only frame
  cannot cancel a pending turnover that tracking supports.
- **Team changes.** A change needs 1.0 s of support, because CHALLENGE.md asks
  for controlled possession rather than a touch. A frame without decisive
  evidence (often a missing ball) pauses the count instead of resetting it, and
  support older than 6 s is dropped. Once confirmed, the boundary moves back to
  the start of its latest support run; the first change after a restart signal
  takes the restart frame when it follows within 2 s.
- **Stoppages.** E3's confirmed stop enters D after two frames (E3 has already
  waited 0.6 s). Leaving a confirmed stop needs E3's live-motion or restart
  evidence; team evidence alone can end it only after 3 s, so a missed restart
  cannot pin D indefinitely.
- **Periods.** Each half starts in D with no memory of the previous one. Half 1
  is graded from its kickoff and is live from its first graded frame. Half 2 is
  graded from before its kickoff (FAQ.md), so it stays D until E3 confirms play
  started, and never before the half's first `Kick Off (Start)` tag frame; a
  half without such a tag falls back to E3's confirmation alone. X is used only
  for ungraded frames.

Known limits: possessions shorter than about 1 s can be missed; stops are
labelled when E3 confirms them, not when the ball went dead; stoppages inside the
pitch without a set-piece tag are not detected; live play whose team is unknown
stays D; the 3 s fallback can end a stop on team evidence alone (including tags)
without proof that play resumed; a stale opposing tag during a long ball
occlusion can create a brief turnover; a start tag that begins early or late
shifts the second-half start. All thresholds are engineering choices, not fitted
values, and none was chosen against the public five minutes.

## Training, validation and limitations

E5 uses invented tracking/XML/evidence fixtures only. No training or parameter
selection was performed, and E5 used no external labelled dataset, manual
competition labels, competition assets or public answer labels. Other owners
must confirm training-data provenance before the final document is frozen.
The public five minutes may check pipeline correctness only, never tuning,
selection or accuracy improvement claims.

Synthetic tests cover contracts, absent/disabled tags, frame mismatches, team
swapping, half independence, start-gate behavior, and repeatable export. The
historical pre-merge overlay evidence is retained in
[the E5 handoff](owners/goblin.md); later E2 evidence is in
[the E2 handoff](owners/belek_isken.md). Those results do
not establish hidden-match accuracy. Restricted full-data jobs and exact CSV
hash reproduction on a second laptop remain human-run release requirements.

Use of published answers: the public five minutes were scored once, as a
pipeline check (frame alignment, label meaning), and not used to choose between
versions. The second-half start rule (Decision 11) was checked once, locally,
against the second-half kickoff frame published in FAQ.md, with yes/no answers
only: whether the start tag begins after the early opening it was meant to
prevent, and whether the first second-half possession is at or after the
published kickoff. No threshold or frame was chosen from that check and nothing
was iterated against it.

## Reproduction

Use Python 3.12 and `requirements-team.lock`; run the synthetic suite and setup
smoke test from a clean checkout. Set the local licensed bundle root, then use
[TEAM_README.md](../../TEAM_README.md) to run the
CLI or save the CSV plus private manifest. Records include code/config/input
hashes, environment, seed, runtime and validated output checksum. The final
commit, config, registered team name, public repository URL and second-laptop
checksum confirmation must be recorded at the [release gate](RELEASE.md).
