# Shared interfaces — proposed version 1

Agree on this at the first session; E1 implements the types. These APIs do not
exist yet. Changes require a short PR note and review by affected consumers.

## Conventions

- N is the frame count; full tactical input has N=199319. Synthetic tests may use
  small N. Frames are strictly ordered 0..N-1. Every output has the same row axis.
- Time is seconds, speed m/s. Keep normalised coordinates for homography and
  metre coordinates for distances, explicitly named. Use games.py pitch size.
- Preserve NaN for missing positions and separate validity masks. Never use zero
  to mean a missing location. Distinguish imputed from observed positions.
- Slot membership identifies a team, not a persistent player identity.
- Events use [start_frame, end_frame) intervals after clipping to [0,N]. Convert
  time with the documented rounding convention and test endpoints explicitly.
- H/A/D are inference states. X is an output abstention, not a fourth possession
  state. Official masks determine excluded video regions; reset each half.
- All functions return new outputs without mutating shared inputs. Configurations
  are explicit, serialisable, versioned, and do not include local absolute paths.

## Data owner output

`load_match(data_dir, config) -> MatchData`

| Field | Shape / meaning |
|---|---|
| frame | int64 [N], exact ordered video frames |
| half | int8 [N], 0 excluded, 1 first half, 2 second half |
| fps, pitch_m | scalar fps, (length,width) |
| ball_xy_m | float [N,2], NaN when unavailable |
| ball_observed | bool [N] |
| players_xy_m | float [N,P,2], NaN where unavailable |
| player_observed | bool [N,P] |
| slot_team | [P], H or A; reject unknown mapping |
| ball_speed_mps | optional float [N], with source and validity documented |
| events | list of frame intervals, code, original tag dictionary |
| metadata | schema version and source identifiers; local provenance kept private |

Use the starter loaders or a tested raw parser. Optional homography/video access
must not force every consumer to decode video. Do not expose GT through this API.

## Feature owner output

`build_features(match, config) -> FeatureData`

FeatureData carries `frame`, named [N] arrays, a validity mask for each feature,
`team_evidence` float [N,2] ordered H,A, and `team_reliability` float [N].

Initial features: distance to each team's nearest player, next-nearest distance,
distance advantage, ball speed, ball-speed validity, ball missing duration,
motion reliability, local density, and boundary proximity. Additional features
must document units and missing-value behavior.

Evidence is a bounded heuristic, not a claim of calibrated probability. H/A
entries are finite, nonnegative, sum to one. No team evidence => [0.5,0.5] with
reliability 0. Reliability lies in [0,1]. E2 alone owns temporal possession state.

## Dead-ball/tag owner output

`build_priors(match, features, config) -> PriorData`

| Field | Shape / meaning |
|---|---|
| dead_evidence | float [N], [0,1], larger means stronger dead-ball evidence |
| dead_reliability | float [N], [0,1]; 0 means no useful signal |
| restart_evidence | float [N], [0,1], not a guaranteed exact restart timestamp |
| tag_team_evidence | float [N,2], H/A conditional on live play |
| tag_team_reliability | float [N], [0,1] |
| diagnostic_flags | local reason codes; not private data in committed docs |

No dead-ball evidence => 0.5 with reliability 0. Unknown team => [0.5,0.5] with
reliability 0. A throw-in can have restart evidence while its team reliability
is zero. Overlapping tags require a documented conflict policy. Do not count
multiple correlated tags as independent votes.

## State owner output

`decode(match, features, priors, config) -> Prediction`

Prediction contains labels [N] in H/A/D/X and optional local diagnostics (state
confidence, transition reasons, candidate boundaries). H/A evidence, stop evidence,
and restart evidence enter one explicitly documented fusion policy. Neutral or
unreliable inputs cannot silently become confident predictions.

Process halves independently. Write X outside the published graded intervals.
Do not carry the first half's state across halftime. Within a half, document how
initial uncertainty and long missing stretches are handled; do not infer D from
absence alone. Keep all thresholds in the configuration and express durations
in seconds before converting to frames.

## Integration and CLI

E5: `predict_match(data_dir, config) -> Prediction` composes loader, features,
priors, and decoding. E1: `write_submission(prediction, path)` writes exact
`frame,label` CSV rows in UTF-8 with stable newlines, no extra index, no blanks.

E1's CLI loads configuration and calls E5's pipeline, then E1's exporter. E4's
checker invokes the official validator. The prediction package must not import
or load public GT. Scoring is a separate explicit operation with a recorded purpose.

Every owner contributes one small synthetic input/output example and tests
invalid shapes, masks, units, or label ordering relevant to their module. E5
checks the composed pipeline against those examples before any full-data run.
