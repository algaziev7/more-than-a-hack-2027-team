"""Small invented match inputs shared by E1–E5 tests."""

import numpy as np

from possession.contracts import FeatureData, MatchData, Prediction, PriorData


def synthetic_match():
    """Eight invented frames, two slots, a missing ball, and a half reset."""
    ball = np.array([[10, 20], [11, 20], [np.nan, np.nan], [np.nan, np.nan],
                     [np.nan, np.nan], [60, 30], [61, 30], [62, 30]], dtype=float)
    players = np.tile(np.array([[[10., 20.], [60., 30.]]]), (8, 1, 1))
    players[2, 1] = np.nan
    return MatchData(
        frame=np.arange(8, dtype=np.int64),
        half=np.array([0, 1, 1, 1, 0, 2, 2, 0], dtype=np.int8),
        fps=25., pitch_m=(105.3, 68.), ball_xy_m=ball,
        ball_observed=np.isfinite(ball).all(axis=1), players_xy_m=players,
        player_observed=np.isfinite(players).all(axis=2),
        slot_team=np.array(["H", "A"]),
        events=[{"start_frame": 1, "end_frame": 3, "start_s": .04,
                 "end_s": .12, "code": "BUILD UP", "tags": {"Team": "Barcelona"}}],
        metadata={"schema_version": 1, "source": "synthetic",
                  "period_start": {"1": "live_at_entry", "2": "live_at_entry"}},
    )


def neutral_features(match):
    n = len(match.frame)
    return FeatureData(match.frame.copy(), {}, {}, np.full((n, 2), .5), np.zeros(n))


def neutral_priors(match):
    n = len(match.frame)
    return PriorData(np.full(n, .5), np.zeros(n), np.zeros(n),
                     np.full((n, 2), .5), np.zeros(n))


def synthetic_prediction():
    """Fixture labels are invented expectations, never competition labels."""
    return Prediction(np.array(list("XHHXXAAX")))
