"""Conservative stoppage/restart evidence, using only canonical match inputs.

This is a heuristic prior, not a referee-state classifier or possession decoder.
It does not open files or read ground truth. See docs/team/DEAD_BALL.md.
"""

from dataclasses import dataclass, fields
import math
from numbers import Real

import numpy as np

from possession.contracts import FeatureData, MatchData, PriorData, validate_frame
from possession.tagging import TaggingConfig, build_tagging_priors

# Preserve tagging's existing bits 1, 2, and 4.
STOP_TAG_AND_STILL = 8
STOP_OUTSIDE_AND_STILL = 16
LIVE_MOTION = 32
CONFIRMED_RESTART = 64
UNUSABLE_BALL = 128


@dataclass(frozen=True)
class DeadBallConfig:
    """Untuned starting thresholds. Times are seconds and distances are metres."""

    enabled: bool = True
    stationary_speed_mps: float = 0.5
    moving_speed_mps: float = 2.0
    max_ball_speed_mps: float = 45.0
    outside_margin_m: float = 0.5
    position_margin_m: float = 10.0
    stop_duration_s: float = 0.6
    motion_duration_s: float = 0.2
    restart_context_s: float = 3.0
    evidence_weight: float = 0.5

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("dead_ball.enabled must be a boolean")
        for field in fields(self):
            if field.name == "enabled":
                continue
            value = getattr(self, field.name)
            if (isinstance(value, bool) or not isinstance(value, Real)
                    or not math.isfinite(value)):
                raise ValueError("dead_ball.{} must be a finite number".format(field.name))
        if not 0 <= self.stationary_speed_mps < self.moving_speed_mps < self.max_ball_speed_mps:
            raise ValueError("ball speeds must satisfy 0 <= stationary < moving < maximum")
        if not 0 < self.outside_margin_m <= self.position_margin_m:
            raise ValueError("margins must satisfy 0 < outside_margin_m <= position_margin_m")
        if min(self.stop_duration_s, self.motion_duration_s, self.restart_context_s) <= 0:
            raise ValueError("stop, motion, and restart-context durations must be positive")
        if not 0 <= self.evidence_weight <= 1:
            raise ValueError("dead_ball.evidence_weight must be in [0, 1]")


def _section(config, name, cls):
    options = config.get(name, {})
    if not isinstance(options, dict):
        raise ValueError("{} settings must be an object".format(name))
    if set(options) - {field.name for field in fields(cls)}:
        raise ValueError("unknown {} setting".format(name))
    return cls(**options)


def _validate_inputs(match, features):
    if not isinstance(match, MatchData):
        raise TypeError("match must be MatchData")
    match.validate()
    if features is None:
        return
    if not isinstance(features, FeatureData):
        raise TypeError("features must be FeatureData or None")
    validate_frame(features.frame)
    if not np.array_equal(features.frame, match.frame):
        raise ValueError("features and match must use the same frame timeline")
    # Recheck shared contracts in case a caller mutated an array after creation.
    FeatureData(features.frame, features.features, features.validity,
                features.team_evidence, features.team_reliability)


def _motion(match, settings):
    """Require credible observations; use displacement to check supplied speeds.

    Returns usable, still, moving, and outside-pitch distance. Without an ATD
    speed, derive motion from adjacent observed frames in the same half only.
    Do not bridge gaps or calculate huge deltas from obviously bad coordinates.
    """
    n = len(match.frame)
    xy = match.ball_xy_m
    length, width = match.pitch_m
    margin = settings.position_margin_m
    position_ok = (match.ball_observed & (match.half > 0)
                   & (xy[:, 0] >= -margin) & (xy[:, 0] <= length + margin)
                   & (xy[:, 1] >= -margin) & (xy[:, 1] <= width + margin))
    displacement_speed = np.full(n, np.nan)
    pairs = np.flatnonzero(position_ok[1:] & position_ok[:-1]
                           & (match.half[1:] == match.half[:-1])) + 1
    displacement_speed[pairs] = np.linalg.norm(xy[pairs] - xy[pairs - 1], axis=1) * match.fps

    raw = match.ball_speed_mps
    if raw is None:
        raw = np.full(n, np.nan)
    has_raw, has_delta = np.isfinite(raw), np.isfinite(displacement_speed)
    usable = position_ok & (has_raw | has_delta)
    usable &= ~has_raw | (raw <= settings.max_ball_speed_mps)
    usable &= ~has_delta | (displacement_speed <= settings.max_ball_speed_mps)
    # A static coordinate with a fast supplied speed, or vice versa, is not
    # affirmative stop/motion evidence. Agreement is required when both exist.
    still = usable & (~has_raw | (raw <= settings.stationary_speed_mps))
    still &= ~has_delta | (displacement_speed <= settings.stationary_speed_mps)
    moving = usable & (~has_raw | (raw >= settings.moving_speed_mps))
    moving &= ~has_delta | (displacement_speed >= settings.moving_speed_mps)
    outside = np.maximum.reduce((np.zeros(n), -xy[:, 0], xy[:, 0] - length,
                                 -xy[:, 1], xy[:, 1] - width))
    return usable, still, moving, outside


def build_priors(match, features=None, config=None) -> PriorData:
    """Combine tagging with sustained stoppage/live evidence in shared PriorData.

    config is the full pipeline dictionary: this stage reads only `tagging`
    and `dead_ball`. features is optional until Beks's module is available.
    No feature-dictionary keys are assumed; only its existing team evidence and
    reliability can corroborate live motion. Input arrays are never changed.

    Missing or unreliable observations give no dead/live opinion and reset
    local confirmation context. Every temporal counter resets at a half change.
    Evidence starts at confirmation, with no retrospective boundary editing.
    """
    _validate_inputs(match, features)
    config = {} if config is None else config
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    settings = _section(config, "dead_ball", DeadBallConfig)
    tagging = _section(config, "tagging", TaggingConfig)
    n = len(match.frame)
    out = build_tagging_priors(match.events, n, tagging)

    # Clues outside the supplied half masks must not leak into inference.
    excluded = match.half == 0
    out.tag_team_evidence[excluded] = .5
    out.tag_team_reliability[excluded] = 0
    out.restart_evidence[excluded] = 0
    out.diagnostic_flags[excluded] = 0
    if not settings.enabled or settings.evidence_weight == 0 or n == 0:
        return out

    usable, still, moving, outside = _motion(match, settings)
    inside = (match.ball_observed & (match.ball_xy_m[:, 0] >= 0)
              & (match.ball_xy_m[:, 0] <= match.pitch_m[0])
              & (match.ball_xy_m[:, 1] >= 0)
              & (match.ball_xy_m[:, 1] <= match.pitch_m[1]))
    tag_window = out.restart_evidence > 0
    tagged_stop = still & tag_window
    outside_stop = still & (outside >= settings.outside_margin_m)
    stop_candidate = tagged_stop | outside_stop
    control = np.zeros(n, dtype=bool)
    if features is not None:
        # Moderate, explicit starting cutoffs; these are not calibrated odds.
        control = ((features.team_reliability >= .5)
                   & (features.team_evidence.max(axis=1) >= .75))

    stop_frames = max(1, math.ceil(settings.stop_duration_s * match.fps))
    motion_frames = max(1, math.ceil(settings.motion_duration_s * match.fps))
    context_frames = max(1, math.ceil(settings.restart_context_s * match.fps))
    stop_run = motion_run = 0
    last_stop = None
    restart_emitted = False
    previous_half = 0
    for frame in range(n):
        half = int(match.half[frame])
        if half != previous_half:
            stop_run = motion_run = 0
            last_stop = None
            restart_emitted = False
        previous_half = half
        if half == 0 or not usable[frame]:
            stop_run = motion_run = 0
            last_stop = None
            restart_emitted = False
            if half:
                out.diagnostic_flags[frame] |= UNUSABLE_BALL
            continue

        stop_run = stop_run + 1 if stop_candidate[frame] else 0
        if stop_run >= stop_frames:
            out.dead_evidence[frame] = .9
            out.dead_reliability[frame] = settings.evidence_weight
            if tagged_stop[frame]:
                out.diagnostic_flags[frame] |= STOP_TAG_AND_STILL
            if outside_stop[frame]:
                out.diagnostic_flags[frame] |= STOP_OUTSIDE_AND_STILL
            last_stop = frame
            restart_emitted = False

        recent_stop = last_stop is not None and 0 < frame - last_stop <= context_frames
        live_candidate = inside[frame] and moving[frame] and (recent_stop or control[frame])
        motion_run = motion_run + 1 if live_candidate else 0
        if motion_run >= motion_frames:
            out.dead_evidence[frame] = .1
            out.dead_reliability[frame] = settings.evidence_weight
            out.diagnostic_flags[frame] |= LIVE_MOTION
            # A single pulse when motion is confirmed after an observed stop.
            # A bare tag keeps its original weaker window-shaped clue.
            if recent_stop and not restart_emitted:
                out.restart_evidence[frame] = max(out.restart_evidence[frame], .75)
                out.diagnostic_flags[frame] |= CONFIRMED_RESTART
                restart_emitted = True

    # Validate the complete result using the unchanged shared contract.
    return PriorData(out.dead_evidence, out.dead_reliability, out.restart_evidence,
                     out.tag_team_evidence, out.tag_team_reliability,
                     out.diagnostic_flags)
