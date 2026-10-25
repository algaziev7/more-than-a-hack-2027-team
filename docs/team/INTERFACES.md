# How the team's modules pass data to each other

Almaz's tagging helper is merged on main; its usage is explained in
[TAGGING.md](TAGGING.md). E1's contracts, loader, exporter and CLI are implemented
on `e1/data-contract` (PR #2), pending consumer review and merge. Feature building,
combined priors, decoding and the integrated pipeline remain planned. See
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

Implemented on E1's branch: `load_match(data_dir, config) -> MatchData`.

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

Available now:

```python
from possession.tagging import load_tagging_signals, build_tagging_signals

# Read the local XML once:
signals = load_tagging_signals()

# Or, if events are already loaded, use this instead:
# signals = build_tagging_signals(events, n_frames=199319)
```

The fields below plus `frame` are returned as ordinary Python lists. Team hints
are pairs ordered H,A. No extra package is needed. NumPy users can convert each
list with `np.asarray`. See [TAGGING.md](TAGGING.md) for the steps Belek and Isken
should follow.

The later combined function is still planned:
`build_priors(match, features, config) -> PriorData`.
It will also use Beks's movement features to help detect stoppages.

| Field | Meaning |
|---|---|
| dead_evidence | float [N]: 0–1 clue about stopped play; 0.5 means neutral |
| dead_reliability | float [N]: weight from 0 to 1; zero means ignore it |
| restart_evidence | float [N]: 0–1 clue that a restart happens around this time |
| tag_team_evidence | float [N,2]: team hints in H,A order |
| tag_team_reliability | float [N]: weight from 0 to 1 for the team hint |
| diagnostic_flags | Optional integer [N] array: codes or bit flags for conflicts or missing information |

The E1 `PriorData` constructor defaults `diagnostic_flags` to None. Convert
Almaz's list outputs to NumPy arrays when constructing the shared contracts.

For now, `dead_evidence` is always 0.5 and `dead_reliability` is always 0:
actual stoppage detection is not implemented. An unknown team gives `(0.5,0.5)`
with weight 0. A throw-in can provide a restart clue without naming a team.

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
