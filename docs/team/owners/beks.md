# Beks — Tracking features and evaluation

- Owner: Beks
- Status: v1 merged (PR #8); reliability diagnosis in progress
- Branch: `e4/reliability-v1` (v1 was `e4/features-v1`)
- Reviewer: E3
- Owned files: `possession/features.py`, `scripts/check_solution.py`, feature tests and evaluation policy
- Last update: 2026-11-10

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

## PR #6 re-review (2026-11-10)

Approved head `9883b4d`. Both findings above are fixed with regression tests:
confirmed live/restart evidence clears pending D, and
`live_confirmed_threshold >= dead_threshold` is rejected. The new 6 s
`evidence_window_s` is validated against every dwell. Merged locally with
`main` at `aa73103`, all 174 tests passed. Non-blocking, read from code and not
tested: the restart route can still set and clear the Decision 6 latch on one
frame if `dead_evidence >= 0.6 + 0.5 * restart_evidence` while
`restart_evidence >= 0.6`. Almaz to confirm E3 never emits that.

## Reliability below the 0.25 cutoff (diagnosis, 2026-11-10)

The coverage run reported about 40% of frames with tracking evidence below
the decoder's `team_reliability_min = 0.25`. Reliability is the product
`proximity * margin * speed_weight`, each in [0, 1], with
`proximity = 1 - nearest / 3 m`. Structural finding, from the formula and
not from match data: with cutoff c, a nearest player beyond `3 * (1 - c)` m
can never count, however far the other team is. At 0.25 that is 2.25 m,
the outer 44% of the 3 m control disc's area if positions were uniform
(19% at 0.10, 28% at 0.15, 36% at 0.20). Contested distances and fast balls
lower it further. The decoder also requires `team_margin_threshold = 0.15`
on the same margin factor that reliability already contains, so margin is
counted twice. The proximity-cap hypothesis was wrong: Beks ran the
breakdown locally (counts kept local) and the contested-margin factor, not
proximity, is the main cause. Fast balls are a small share.

Tooling: `reliability_breakdown(features, cutoff)` in `possession/features.py`
assigns each low frame to "far", "contested" or "fast" (the first factor
that takes the product under the cutoff). `scripts/reliability_breakdown.py`
runs it locally and prints aggregate counts only. Synthetic test:
`test_reliability_breakdown_names_the_factor_that_drops_each_frame`.

Options to decide with Belek (E2), none selected: (a) keep the formula and
lower the cutoff; (b) make proximity a gentler ramp (for example full weight
inside 1 m) so a lone nearby player still counts; (c) drop the decoder's
separate margin check or the margin factor from reliability, so it is not
counted twice. No labels exist to choose between them, so the argument must
come from synthetic cases and coverage counts, never public-window scores.

Proposed (E4, not yet agreed with E2): option (c), drop the margin factor so
`reliability = proximity * speed_weight` and let the decoder's
`team_margin_threshold` alone judge contested frames. Synthetic geometry
(slow ball, decoder margin 0.15) under current / (a) cutoff 0.15 / (c):

| Nearest, other team | Margin | Current | (a) | (c) |
|---|---|---|---|---|
| 1.0 m, 2.0 m | 0.33 | no | yes | yes |
| 1.5 m, 2.5 m | 0.25 | no | no | yes |
| 2.0 m, 6.0 m | 0.50 | no | yes | yes |
| 0.5 m, 0.7 m | 0.17 | no | no | yes |
| 1.0 m, 1.2 m | 0.09 | no | no | no |
| 2.4 m, 9.0 m | 0.58 | no | no | no |

Argument: a player 1 m from the ball with the nearest opponent 2 m away is
ordinary possession, and the current rule rejects it because the same margin
is penalised twice. (c) states each fact once: reliability says how much to
trust the geometry, margin says how decisive it is. (a) only shifts the
cutoff and still double-counts. Risks: (c) accepts close duels just above
margin 0.15 (row 4), and in contested frames tracking keeps high reliability
with evidence near 0.5, so in the reliability-weighted fusion it outweighs a
tag instead of letting the tag fill the gap. That interacts with E2's
planned "tags fill gaps" fusion change and must be decided together.
Reliability is a shared interface, so E2 agrees before E4 changes it.

## Next exact action

Beks sends Belek the proposal above. If Belek agrees, Beks changes
`build_features` on this branch, updates the synthetic tests, reruns the
breakdown locally (counts stay local), and opens the PR with E2 and E3
notified. Belek decides how fused evidence treats contested tracking.
Almaz re-reviews PR #6 so it can merge. After E1 produces the final CSV,
Beks runs `scripts/check_solution.py` on that exact file.
