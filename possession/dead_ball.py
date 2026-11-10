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
    max_missing_gap_s: float = 0.0
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
        if not 0 <= self.max_missing_gap_s <= self.stop_duration_s:
            raise ValueError("max_missing_gap_s must be between zero and stop_duration_s")


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

    Missing observations give no dead/live opinion. An optional bounded gap
    budget preserves stop support without counting missing frames as evidence.
    Rejected observations and half changes always reset local context.
    Evidence starts at confirmation, with no retrospective boundary editing.
    """
    return _build_priors(match, features, config)


def _build_priors(match, features, config, totals=None):
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
    if totals is not None:
        totals.update(
            graded_frames=int(np.count_nonzero(~excluded)),
            ball_observed_frames=int(np.count_nonzero(match.ball_observed & ~excluded)),
        )
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
    if totals is not None:
        totals.update(
            ball_usable_frames=int(usable.sum()),
            ball_missing_frames=int(np.count_nonzero(~match.ball_observed & ~excluded)),
            ball_observed_unusable_frames=int(np.count_nonzero(
                match.ball_observed & ~excluded & ~usable)),
            usable_not_still_frames=int(np.count_nonzero(usable & ~still)),
            still_without_stop_context_frames=int(np.count_nonzero(still & ~stop_candidate)),
            stop_candidate_frames=int(stop_candidate.sum()),
            stop_candidate_below_dwell_frames=0,
            confirmed_stop_runs=0,
            pending_stop_runs_reset_by_unusable_ball=0,
            pending_stop_runs_reset_by_lost_support=0,
            pending_stop_runs_reset_by_half_change=0,
            stop_contexts_followed_by_confirmed_live=0,
        )
    control = np.zeros(n, dtype=bool)
    if features is not None:
        # Moderate, explicit starting cutoffs; these are not calibrated odds.
        control = ((features.team_reliability >= .5)
                   & (features.team_evidence.max(axis=1) >= .75))

    stop_frames = max(1, math.ceil(settings.stop_duration_s * match.fps))
    motion_frames = max(1, math.ceil(settings.motion_duration_s * match.fps))
    context_frames = max(1, math.ceil(settings.restart_context_s * match.fps))
    # Floor keeps the configured maximum a strict upper bound on missing time.
    gap_frames = math.floor(settings.max_missing_gap_s * match.fps)
    stop_run = motion_run = 0
    missing_run = stop_missing = 0
    last_usable = None
    last_stop = None
    restart_emitted = False
    previous_half = 0
    for frame in range(n):
        half = int(match.half[frame])
        if half != previous_half:
            if totals is not None and 0 < stop_run < stop_frames:
                totals["pending_stop_runs_reset_by_half_change"] += 1
            stop_run = motion_run = 0
            last_stop = None
            restart_emitted = False
            missing_run = stop_missing = 0
            last_usable = None
        previous_half = half
        if half == 0 or not usable[frame]:
            motion_run = 0  # Live confirmation must remain consecutive.
            if half and not match.ball_observed[frame]:
                missing_run += 1
                if stop_run:
                    stop_missing += 1
                if (last_usable is not None and missing_run <= gap_frames
                        and stop_missing <= gap_frames):
                    out.diagnostic_flags[frame] |= UNUSABLE_BALL
                    continue
            if totals is not None and half and 0 < stop_run < stop_frames:
                totals["pending_stop_runs_reset_by_unusable_ball"] += 1
            stop_run = motion_run = 0
            last_stop = None
            restart_emitted = False
            missing_run = stop_missing = 0
            last_usable = None
            if half:
                out.diagnostic_flags[frame] |= UNUSABLE_BALL
            continue

        if missing_run and last_usable is not None:
            gap_speed = (np.linalg.norm(match.ball_xy_m[frame] - match.ball_xy_m[last_usable])
                         * match.fps / (frame - last_usable))
            # Reacquiring a stationary ball somewhere else does not establish
            # that it remained still through the unseen interval.
            if gap_speed > settings.stationary_speed_mps:
                if totals is not None and 0 < stop_run < stop_frames:
                    totals["pending_stop_runs_reset_by_lost_support"] += 1
                stop_run = stop_missing = 0
            if gap_speed > settings.max_ball_speed_mps:
                last_stop = None
                restart_emitted = False
        missing_run = 0
        last_usable = frame
        if totals is not None:
            if not stop_candidate[frame] and 0 < stop_run < stop_frames:
                totals["pending_stop_runs_reset_by_lost_support"] += 1
        stop_run = stop_run + 1 if stop_candidate[frame] else 0
        if not stop_candidate[frame]:
            stop_missing = 0
        if totals is not None and stop_candidate[frame]:
            if stop_run < stop_frames:
                totals["stop_candidate_below_dwell_frames"] += 1
            elif stop_run == stop_frames:
                totals["confirmed_stop_runs"] += 1
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
                if totals is not None:
                    totals["stop_contexts_followed_by_confirmed_live"] += 1
                out.restart_evidence[frame] = max(out.restart_evidence[frame], .75)
                out.diagnostic_flags[frame] |= CONFIRMED_RESTART
                restart_emitted = True

    # Validate the complete result using the unchanged shared contract.
    return PriorData(out.dead_evidence, out.dead_reliability, out.restart_evidence,
                     out.tag_team_evidence, out.tag_team_reliability,
                     out.diagnostic_flags)


def summarize_prior_diagnostics(match, features=None, config=None):
    """Return totals only; never frame IDs, arrays, paths, tags, or metadata.

    Re-run the unchanged builder with counters and, if features are supplied,
    compare with no control corroboration. No labels or decoder are consumed.
    All frame shares use graded frames as denominator; zero denominators give
    None. A subsequent live confirmation is a restart, not a cancelled stop.
    """
    totals = {}
    priors = _build_priors(match, features, config, totals)
    active = match.half > 0
    enabled = _section({} if config is None else config, "dead_ball", DeadBallConfig)
    motion_enabled = enabled.enabled and enabled.evidence_weight > 0
    stop = (priors.dead_evidence > .5) & (priors.dead_reliability > 0) & active
    live = (priors.dead_evidence < .5) & (priors.dead_reliability > 0) & active
    totals["confirmed_stop_frames"] = int(stop.sum())
    totals["confirmed_live_frames"] = int(live.sum())
    if motion_enabled and len(match.frame):
        totals["usable_without_confirmed_stop_frames"] = (
            totals["ball_usable_frames"] - totals["confirmed_stop_frames"])
    frame_counts = {name: value for name, value in totals.items() if name.endswith("frames")}
    event_counts = {name: value for name, value in totals.items() if not name.endswith("frames")}
    graded = totals["graded_frames"]
    result = {
        "motion_enabled": motion_enabled,
        "frame_counts": frame_counts,
        "graded_frame_shares": {name: value / graded if graded else None
                                for name, value in frame_counts.items()},
        "event_counts": event_counts,
        "confirmed_stop_frames_overwritten_by_live": int(np.count_nonzero(
            ((priors.diagnostic_flags & (STOP_TAG_AND_STILL | STOP_OUTSIDE_AND_STILL)) != 0)
            & live)),
        "confirmed_stop_run_share_followed_by_live": (
            totals["stop_contexts_followed_by_confirmed_live"] / totals["confirmed_stop_runs"]
            if totals.get("confirmed_stop_runs") else None),
    }
    if features is not None:
        baseline = build_priors(match, features=None, config=config)
        baseline_stop = (baseline.dead_evidence > .5) & (baseline.dead_reliability > 0) & active
        result["without_control_comparison"] = {
            "confirmed_stop_frames_without_control": int(baseline_stop.sum()),
            "confirmed_stop_frames_with_control": int(stop.sum()),
            "changed_stop_frames": int(np.count_nonzero(stop != baseline_stop)),
            "additional_live_frames_with_control": int(np.count_nonzero(
                live & ~((baseline.dead_evidence < .5) & (baseline.dead_reliability > 0)))),
        }
    return result
