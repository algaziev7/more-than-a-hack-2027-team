"""Frame-aligned tracking clues, with no possession state or file access."""

import numpy as np

from possession.contracts import FeatureData, MatchData


# Untuned v1 geometry and tracking-quality cutoffs.
CONTROL_RADIUS_M = 3.0
NEARBY_RADIUS_M = 5.0
BALL_POSITION_MARGIN_M = 10.0
MAX_BALL_SPEED_MPS = 45.0
MAX_SLOT_SPEED_MPS = 15.0
MAX_SPEED_DISAGREEMENT_MPS = 3.0
FAST_BALL_MPS = 8.0


def _displacement_speed(xy, same_half, fps):
    speed = np.full(xy.shape[:-1], np.nan)
    delta = xy[1:] - xy[:-1]
    speed[1:] = np.where(same_half, np.hypot(delta[..., 0], delta[..., 1]) * fps, np.nan)
    return speed


def _team_distances(distances):
    nearby = (distances <= NEARBY_RADIUS_M).sum(axis=1)
    if distances.shape[1] >= 2:
        distances.partition(1, axis=1)
        nearest, next_nearest = distances[:, 0], distances[:, 1]
    else:
        nearest = distances.min(axis=1, initial=np.inf)
        next_nearest = np.full(len(distances), np.inf)
    return (np.where(np.isfinite(nearest), nearest, np.nan),
            np.where(np.isfinite(next_nearest), next_nearest, np.nan),
            np.where(np.isfinite(nearest), nearby, np.nan))


def build_features(match, config=None) -> FeatureData:
    """Compute tracking evidence from MatchData. V1 has no config overrides."""
    if not isinstance(match, MatchData):
        raise TypeError("match must be MatchData")
    match.validate()
    active = match.half > 0
    same_half = active[1:] & (match.half[1:] == match.half[:-1])

    ball_x, ball_y = match.ball_xy_m.T
    length, width = match.pitch_m
    boundary = np.minimum.reduce((ball_x, ball_y, length - ball_x, width - ball_y))
    ball_usable = active & match.ball_observed & (boundary >= -BALL_POSITION_MARGIN_M)
    ball_xy = np.where(ball_usable[:, None], match.ball_xy_m, np.nan)
    displacement = _displacement_speed(ball_xy, same_half, match.fps)
    # shortcut: a single outlier can spoil two deltas, revisit if eligible data shows excessive loss.
    ball_usable &= ~(displacement > MAX_BALL_SPEED_MPS)

    raw_speed = match.ball_speed_mps
    if raw_speed is None:
        raw_speed = np.full(len(match.frame), np.nan)
    disagreement = np.abs(raw_speed - displacement)
    speed = np.where(np.isfinite(raw_speed), raw_speed, displacement)
    speed_usable = ball_usable & (speed <= MAX_BALL_SPEED_MPS)
    speed_usable &= ~(disagreement > MAX_SPEED_DISAGREEMENT_MPS)

    # Count true observation gaps separately from rejected tracking samples.
    missing = active & ~match.ball_observed
    last_seen = np.where(missing, -1, match.frame)
    last_seen[1:] = np.maximum(last_seen[1:], np.where(same_half, -1, match.frame[1:] - 1))
    missing_seconds = (match.frame - np.maximum.accumulate(last_seen)) / match.fps

    slot_speed = _displacement_speed(match.players_xy_m, same_half[:, None], match.fps)
    slot_usable = match.player_observed & ~(slot_speed > MAX_SLOT_SPEED_MPS)
    player_x, player_y = np.moveaxis(match.players_xy_m, -1, 0)
    distances = np.hypot(player_x - ball_x[:, None], player_y - ball_y[:, None])
    distances[~(ball_usable[:, None] & slot_usable)] = np.inf
    home, home_second, home_count = _team_distances(distances[:, match.slot_team == "H"])
    away, away_second, away_count = _team_distances(distances[:, match.slot_team == "A"])

    closest = np.minimum(home, away)
    supported = (boundary >= 0) & (closest < CONTROL_RADIUS_M) & (home != away)
    home_support = np.full(len(match.frame), .5)
    np.divide(away, home + away, out=home_support, where=supported)
    proximity = np.where(supported, 1 - closest / CONTROL_RADIUS_M, 0)
    # A rejected raw speed must not erase observed fast movement from the team clue.
    clue_speed = np.where(speed_usable, speed, displacement)
    speed_weight = FAST_BALL_MPS / np.fmax(clue_speed, FAST_BALL_MPS)
    reliability = proximity * np.abs(2 * home_support - 1) * speed_weight

    features = {
        "home_nearest_m": home,
        "home_next_nearest_m": home_second,
        "away_nearest_m": away,
        "away_next_nearest_m": away_second,
        "home_distance_advantage_m": away - home,
        "home_nearby_count": home_count,
        "away_nearby_count": away_count,
        "ball_boundary_distance_m": np.where(ball_usable, boundary, np.nan),
        "ball_missing_duration_s": np.where(active, missing_seconds, np.nan),
        "ball_speed_mps": np.where(speed_usable, speed, np.nan),
        "ball_speed_disagreement_mps": np.where(ball_usable, disagreement, np.nan),
    }
    return FeatureData(
        match.frame.copy(), features, {name: np.isfinite(value) for name, value in features.items()},
        np.column_stack((home_support, 1 - home_support)), reliability,
    )
