# Beks — Tracking features and evaluation

- Owner: Beks
- Status: v1 implemented and verified on synthetic inputs
- Branch: `e4/features-v1`
- Reviewer: E3
- Owned files: `possession/features.py`, `scripts/check_solution.py`, feature tests and evaluation policy
- Last update: 2026-11-09

## Feature handoff

`build_features(match, config)` returns the existing `FeatureData` contract.
All feature arrays have one float per tactical frame and a matching Boolean
validity mask. Unavailable values are NaN. Frames outside the half masks have
no valid features and neutral team evidence.

| Feature | Meaning |
|---|---|
| `home_nearest_m`, `away_nearest_m` | Distance from ball to closest usable slot on each team |
| `home_next_nearest_m`, `away_next_nearest_m` | Distance to the second closest usable slot |
| `home_distance_advantage_m` | Away nearest minus home nearest. Positive favors H |
| `home_nearby_count`, `away_nearby_count` | Usable slots within 5 m. Zero is valid if a team has a usable slot farther away |
| `ball_boundary_distance_m` | Minimum signed distance to the four pitch sides. Negative means outside |
| `ball_missing_duration_s` | Elapsed consecutive missing frames divided by fps. Zero on observed frames, including rejected positions |
| `ball_speed_mps` | Supplied speed or adjacent observed displacement times fps. Invalid if either source exceeds 45 m/s or the two differ by over 3 m/s |
| `ball_speed_disagreement_mps` | Absolute difference when both speed sources exist and ball position is usable |

Positions more than 10 m beyond a pitch side and ball jumps over 45 m/s
are unusable for geometry. Displacement uses adjacent observations in the
same half. A slot jump over 15 m/s excludes that slot for the current frame.
The code uses slot displacement only as a quality check. An isolated position
outlier can also invalidate the displacement into the following frame.

The H/A clue requires an in-pitch ball and a distance to each team, with a
unique nearest team closer than 3 m. Home support is the away distance divided
by the sum of both distances, with away support as its complement.
Reliability falls with distance to the ball, closeness of the two team
distances, and ball speed above 8 m/s. If a supplied speed is rejected,
adjacent displacement can still reduce reliability. With neither source
the distance clue is unchanged. Unavailable or ambiguous evidence is `(0.5, 0.5)` with
reliability zero. These are untuned heuristics. The function accepts the
pipeline config and v1 uses fixed constants. E2 owns persistence and labels.

## Verification and PR #6 review

- Base: `158a961`. On Windows Python 3.12.10, NumPy 2.2.6 and pandas 3.0.3,
  `python -m unittest tests.test_features tests.test_check_solution` passed
  all 13 E4 tests. The full suite ran 110 tests with the same E1 failure as
  baseline. E1 accepts `/private/local` on Windows because
  `Path.is_absolute()` returns false. `python scripts/check_setup.py` passed.
- A 199,319-frame, 22-slot invented match produced valid features. A 72-frame
  invented match passed E4 -> E3 -> PR #6 at `96663a8` -> E1 export -> official
  format validation, with expected H/A transitions and half reset. The 43
  decoder tests on that PR head passed separately. The combined checkout
  passed 152 of 153 tests, with only the existing E1 Windows failure.
- In PR #6 at `96663a8`, pending D dwell can survive confirmed live motion
  when neither team has a decisive clue. With invented tracking, two isolated
  E3 stop confirmations at frames 47 and 72 were separated by a confirmed
  restart at 52 and live evidence at 52–57. The decoder still entered D at
  72 by counting the stale clue from 47. E2 should clear pending D support
  on positive live/restart evidence while continuing to tolerate neutral gaps.
- PR #6 accepts `live_confirmed_threshold=0.9`, which lets the same reliable
  E3 clue both confirm and clear the stop latch. With a stationary ball and
  a throw-in tag, the decoder left D on team proximity alone. E2 should
  prevent the configured live and dead thresholds from overlapping.

## Evaluation policy

- Run `python scripts/check_solution.py path/to/team.csv` on the exact final
  CSV. It forwards the official validator's output and exit status and
  defaults to the full tactical frame count. A pass establishes format only.
- For each experiment record the commit, config, purpose, evidence source,
  parameter-selection method and result. Synthetic cases establish logic
  and regression coverage. Unlabelled local diagnostics describe behavior.
- The public five-minute labels are for pipeline sanity checks only.
  Prediction must work with ground truth unavailable. Training, tuning and
  candidate selection using labels require eligible, documented labels from
  other matches. Split by match and compare frozen candidates on held-out
  matches. Use paired temporal or match-level resampling where warranted.
- Keep restricted assets, extracts and private diagnostics local and out of
  Git and hosted AI tools. Full-match accuracy and improvement are unverified.

## Next exact action

Almaz reviews the feature thresholds and evidence semantics. Belek and Isken
review the pending-D counterexample. E5 wires the feature builder into the
pipeline, then an authorised teammate can run a local match smoke test and
validate the exact CSV. The timeboxed search for eligible other-match labels
and accuracy validation remain open.
