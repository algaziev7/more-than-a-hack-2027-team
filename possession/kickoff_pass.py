"""Experimental controlled-pass evidence, NOT kickoff confirmation.

A preparatory pass can satisfy this detector too. Do not wire its output into
the half-start gate without independent evidence and E2/E4 review.
"""

from collections import deque
import math

import numpy as np

from possession.dead_ball import (
    DeadBallConfig, _kickoff_context, _motion, _section, _validate_inputs,
)
from possession.features import CONTROL_RADIUS_M


def controlled_pass_candidates(match, features, config=None):
    """Return bool[N] reception-time candidates using existing E3/E4 settings.

    Requires start-tag context, bounded spatial settlement, control near the
    kick, sustained observed release beyond both teams' control radius, and
    fresh control at reception. Does not require an absolute centre location.
    No final labels, interpolation, file access, or retrospective boundaries.
    """
    _validate_inputs(match, features)
    config = {} if config is None else config
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    settings = _section(config, "dead_ball", DeadBallConfig)
    out = np.zeros(len(match.frame), dtype=bool)
    if not settings.enabled or settings.evidence_weight == 0 or features is None:
        return out
    keys = ("home_nearest_m", "away_nearest_m")
    if not all(key in features.features for key in keys):
        return out
    home, away = (features.features[key] for key in keys)
    distances_valid = (features.validity[keys[0]] & features.validity[keys[1]]
                       & np.isfinite(home) & np.isfinite(away) & (home >= 0) & (away >= 0))
    separated = distances_valid & (home > CONTROL_RADIUS_M) & (away > CONTROL_RADIUS_M)
    control = ((features.team_reliability >= .5) & (features.team_evidence.max(axis=1) >= .75))
    context = _kickoff_context(match.events, len(match.frame))
    usable, _, moving, _ = _motion(match, settings)
    settle_n = max(1, math.ceil(settings.stop_duration_s*match.fps))
    release_n = max(1, math.ceil(settings.motion_duration_s*match.fps))
    gap_n = math.floor(settings.kickoff_max_missing_gap_s*match.fps)
    episode_n = math.ceil(settings.restart_context_s*match.fps)
    control_n = math.ceil(settings.kickoff_control_window_s*match.fps)
    stable = deque(maxlen=settle_n)
    origin = armed_at = onset = last_control = last_motion = last_observed = None
    previous_half = release_run = missing = 0
    released = kick_control = False
    for i in range(len(match.frame)):
        half = int(match.half[i])
        if half != previous_half or not half or not context[i]:
            stable.clear()
            origin = armed_at = onset = last_control = last_motion = last_observed = None
            release_run = missing = 0
            released = kick_control = False
        previous_half = half
        if not half or not context[i]:
            continue
        if not match.ball_observed[i]:
            missing += 1
            if missing <= gap_n:
                continue
            stable.clear()
            origin = armed_at = onset = last_control = last_motion = last_observed = None
            release_run = 0
            released = kick_control = False
            continue
        xy = match.ball_xy_m[i]
        valid = usable[i] and np.all(xy >= 0) and np.all(xy <= match.pitch_m)
        fast = moving[i]
        if last_observed is not None and i > last_observed+1:
            speed = np.linalg.norm(xy-match.ball_xy_m[last_observed])*match.fps/(i-last_observed)
            valid = bool(valid and speed <= settings.max_ball_speed_mps)
            fast = bool(fast and speed >= settings.moving_speed_mps)
        if not valid:
            stable.clear()
            origin = armed_at = onset = last_control = last_motion = last_observed = None
            release_run = missing = 0
            released = kick_control = False
            continue
        last_observed = i
        if control[i]:
            last_control = i
        if armed_at is not None:
            if i-armed_at > episode_n:
                origin = armed_at = onset = last_motion = None
                release_run = 0
                released = kick_control = False
            elif fast:
                if onset is None:
                    onset = i
                    kick_control = last_control is not None and i-last_control <= control_n
                last_motion = i
                release_run = release_run+1 if separated[i] else 0
                released |= release_run >= release_n
            else:
                release_run = 0
        if (armed_at is not None and kick_control and released and control[i]
                and last_motion is not None and i-last_motion <= control_n
                and np.linalg.norm(xy-origin) >= settings.kickoff_departure_m):
            out[i] = True
            stable.clear()
            origin = armed_at = onset = last_motion = None
            release_run = missing = 0
            released = kick_control = False
            continue
        # Stable spatial support can tolerate bounded jitter. Supplied fast
        # speed contradicts settlement even when the coordinates look static.
        raw = match.ball_speed_mps
        slow_raw = raw is None or not np.isfinite(raw[i]) or raw[i] <= settings.stationary_speed_mps
        if slow_raw:
            stable.append((i, xy.copy()))
        else:
            stable.clear()
        if (len(stable) == settle_n and stable[-1][0]-stable[0][0] <= settle_n-1+gap_n):
            points = np.array([point for _, point in stable])
            drift_bound = settings.stationary_speed_mps*settings.stop_duration_s
            if np.linalg.norm(points-points[0], axis=1).max() <= drift_bound:
                origin, armed_at = np.median(points, axis=0), i
                onset = last_motion = None
                release_run = missing = 0
                released = kick_control = False
    return out
