# Possession system — technical draft

Status: E5 review branch, 2026-11-10. This is an assembly draft, not a final
submission document. E1/E3/E4 implementations are merged. E2's decoder is in
[PR #6](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/6) and E5's
wiring is on `e5/pipeline-v1`. No final candidate, team-named CSV, cross-laptop
reproduction or full-match accuracy result has been established.

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

An in-pitch ball within 3 m of a unique nearest team provides an H/A distance
clue. Reliability falls with distance, similar opposing distances and fast ball
motion. Cutoffs are untuned engineering heuristics, not fitted probabilities.
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

## Possession rules — E2 pending review

The unmerged decoder at `9883b4d` combines E4/E3 team clues by reliability, uses
separate dead/live evidence and requires dwell before transitions. Ordinary
pending support has bounded age and tolerates neutral gaps. Each half starts
with D and no earlier state; ungraded frames receive X. A confirmed stop latches
D until restart/live evidence or a longer, bounded team-evidence safety valve.
Confirmed live play cancels a pending stop. Configuration prevents overlapping
live/dead thresholds and bare tag restart hints from clearing the stop latch.

These rules aim to avoid pass/deflection flicker, but dwell can delay or miss short
possessions. They are review-branch behavior, not merged E5 policy. E2/E4 must
approve the final description. The unresolved case of confirmed live play with
unknown team can remain D; no new E5 rule resolves it. E2 owns any changes.

## Training, validation and limitations

E5 uses invented tracking/XML/evidence fixtures only. No training or parameter
selection was performed, and E5 used no external labelled dataset, manual
competition labels, competition assets or public answer labels. Other owners
must confirm training-data provenance before the final document is frozen.
The public five minutes may check pipeline correctness only, never tuning,
selection or accuracy improvement claims.

Synthetic tests cover contracts, absent/disabled tags, frame mismatches, team
swapping, half independence and repeatable export. E5 also combined its work
with the unmerged E2 revision in a disposable synthetic checkout. See
[the E5 handoff](owners/goblin.md) for measured test counts. Those results do
not establish hidden-match accuracy. Restricted full-data jobs and exact CSV
hash reproduction on a second laptop remain human-run release requirements.

## Reproduction

Use Python 3.12 and `requirements-team.lock`; run the synthetic suite and setup
smoke test from a clean checkout. After reviewed E2/E5 integration, set the local
licensed bundle root, then use [TEAM_README.md](../../TEAM_README.md) to run the
CLI or save the CSV plus private manifest. Records include code/config/input
hashes, environment, seed, runtime and validated output checksum. The final
commit, config, registered team name, public repository URL and second-laptop
checksum confirmation must be recorded at the [release gate](RELEASE.md).
