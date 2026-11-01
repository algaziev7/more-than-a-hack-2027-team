# How the team's modules pass data to each other

Almaz's tagging helper and adapter, plus Azamat's contracts, loader, exporter,
and CLI are merged on main. This branch adds motion-based stopped/live-play
clues in `possession/dead_ball.py`; see [DEAD_BALL.md](DEAD_BALL.md).
Feature building, decoding, and the full pipeline remain planned. See
[SETUP.md](SETUP.md) for concrete constructors and synthetic examples.

Before changing a shared field or function, tell the people who use it and ask
for their review. Azamat owns the shared data types.

## Rules everyone follows

- `N` means the number of video frames. For the full tactical video, N is 199319.
  Tests can use a smaller number.
- Every list or array uses the same frame order: 0, 1, 2, ... N-1. Entry 100 always
  describes tactical frame 100.
- Use seconds for time and metres for distances. Pitch coordinates used with
  homography stay in the 0–1 range. Name fields clearly so units are not mixed.
- Keep missing positions as `NaN`. A separate true/false field says whether a
  position was observed. Do not replace a missing position with (0,0).
- A track slot belongs to a team, but may not follow the same player throughout
  the match.
- An event includes its start frame and excludes its end frame. Start 2, end 5
  means frames 2, 3, and 4. Remove any part outside the video.
- H and A mean live possession; D means play stopped. X means no answer.
  Process the two halves separately.
- Functions should not change their input data. Settings should be easy to save
  with a run. Keep each laptop's private file paths outside shared settings.

## Azamat: load the data

Merged on main: `load_match(data_dir, config) -> MatchData`.

In the table, `[N,2]` means N rows with two values per row. `[N,P,2]` means
positions for P track slots in each of N frames. `bool` means true or false.

| Field | Format and meaning |
|---|---|
| frame | int64 [N]: frame numbers in order |
| half | int8 [N]: 0 outside graded play, 1 first half, 2 second half |
| fps, pitch_m | Frames per second; pitch length and width in metres |
| ball_xy_m | float [N,2]: ball x/y position, or NaN if missing |
| ball_observed | bool [N]: whether the ball position was observed |
| players_xy_m | float [N,P,2]: player x/y positions, with NaN for missing values |
| player_observed | bool [N,P]: whether each slot has an observed position |
| slot_team | [P]: H or A for each slot; unknown mappings cause an error |
| ball_speed_mps | Optional float [N]: speed, with source and validity explained |
| events | Event dictionaries with frame times, code, and tags |
| metadata | Format version and source information; private run details stay local |

Reuse the starter loaders where useful. Loading tracking should not require
reading videos. Do not include the answer file in this input.

## Beks: calculate clues from tracking

Planned function: `build_features(match, config) -> FeatureData`.

Return frame numbers, named feature arrays, and a true/false validity array for
each feature. `FeatureData.features` and `.validity` are dictionaries with
exactly the same keys, containing float[N] arrays and bool[N] masks respectively.
Start with distances to nearby players, distance advantage, ball
speed, movement reliability, missing-ball duration, nearby player counts, and
distance to pitch boundaries. Explain each feature's units and missing values.

Also return:

| Field | Meaning |
|---|---|
| team_evidence | float [N,2]: team hints in H,A order; each pair adds to 1 |
| team_reliability | float [N]: weight from 0 to 1; zero means ignore the hint |

With no useful team evidence, return `(0.5,0.5)` and weight 0. These are clues,
not measured probabilities. Belek and Isken decide when possession changes;
features should not maintain a separate possession state.

## Almaz: clues from tags and stoppages

Use this adapter after loading the match:

```python
from possession.tagging import build_tagging_priors

priors = build_tagging_priors(match.events, n_frames=len(match.frame))
```

`match` is Azamat's `MatchData`. The adapter returns his actual `PriorData`
type, with NumPy arrays ready for Belek and Isken. It preserves every clue and
flag. It checks frame order and uses the shared constructor to check shapes,
lengths, values, and neutral clues. Each result has its own copies of the data.

The original `load_tagging_signals()` and `build_tagging_signals()` still return
Python lists and work without NumPy. If you already have those signals, call
`to_prior_data(signals)` to convert them. Only the adapter needs the NumPy
dependency already used by Azamat's code. See [TAGGING.md](TAGGING.md).

The combined function is implemented on this branch:

```python
from possession.dead_ball import build_priors

priors = build_priors(match, features=features, config=config)
```

`features` is optional; `build_priors(match)` works with Azamat's existing
ball positions/speeds and event tags. If provided, FeatureData must use the
same frames. Only its existing team evidence/reliability is consumed; no new
feature-dictionary keys are required. The shared types are unchanged.

| Field | Meaning |
|---|---|
| dead_evidence | float [N]: 0–1 clue about stopped play; 0.5 means neutral |
| dead_reliability | float [N]: weight from 0 to 1; zero means ignore it |
| restart_evidence | float [N]: 0–1 clue that a restart happens around this time |
| tag_team_evidence | float [N,2]: team hints in H,A order |
| tag_team_reliability | float [N]: weight from 0 to 1 for the team hint |
| diagnostic_flags | Optional integer [N] array: codes or bit flags for conflicts or missing information |

`PriorData` has no frame field. Use `match.frame` for frame numbers. The adapter
passes all diagnostic flags as an integer array; the shared constructor also
allows None for other modules that do not provide flags.

In the combined function, `dead_evidence=0.9` supports stopped play and 0.1
supports live play, with default weight 0.5. No opinion remains 0.5 with weight
0. These are untuned strengths, not measured probabilities. Tagging-only helpers
still return neutral dead-ball fields. Unknown teams remain `(0.5,0.5)` with
weight 0; a throw-in can provide a restart clue without naming a team.

Stop support needs sustained slow observations plus a set-piece window or an
outside-pitch position. Live support needs sustained in-pitch motion plus recent
stop context or reliable team-control evidence. One stronger restart pulse can
follow each confirmed stop. Missing observations and half changes reset history;
excluded frames are neutral. Confirmation already adds a delay, so E2 should
account for it before adding further persistence. Details and reason bits are
in [DEAD_BALL.md](DEAD_BALL.md). Review these semantics with E2/E4 before merging.

Repeated tags must not make a clue stronger. Opposing attacking hints cancel
where they overlap. A restart tag does not identify the exact restart frame.

## Belek and Isken: decide possession

Planned function: `decode(match, features, priors, config) -> Prediction`.

Read Beks's features and Almaz's clues for each frame. Combine their weights
with the state machine's rules to produce one label per frame: H, A, D, or X.
Document how you combine the clues and why you accept a change of possession.
The E1 `Prediction` constructor takes `labels: ndarray` and
`diagnostics: dict` (default empty). Optional debug output can explain decisions.

Reset at each half. Write X outside the published graded intervals. Do not carry
the first half's possessor into the second half. Missing information alone must
not imply stopped play. Keep time thresholds in seconds and convert using fps.

## Goblin and Azamat: run everything and write the CSV

Implemented E1 infrastructure and planned integration:

- Goblin's `predict_match(data_dir, config)` connects loading, features, clues,
  and the state machine.
- Azamat's implemented `write_submission(prediction, path)` writes the exact `frame,label`
  CSV with all frames in order, no extra columns, and no empty labels.
- Azamat's implemented `scripts/predict.py` loads settings, seeds Python/NumPy,
  calls Goblin's pipeline, and saves the CSV. Until that pipeline is available,
  it exits with a clear error and writes no prediction.
- Beks's check calls the official submission validator.

Prediction code must not read the public answer file. Scoring is a separate
step used only as allowed by the competition rules.

Each owner provides a small invented example and tests for their module.
Goblin connects these examples first so problems can be found before running
the full match.
