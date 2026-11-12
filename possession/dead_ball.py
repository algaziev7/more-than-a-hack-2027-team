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
CONFIRMED_KICKOFF = 256


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
    kickoff_centre_radius_m: float = 1.0
    kickoff_departure_m: float = 1.5
    kickoff_control_window_s: float = 1.0
    kickoff_max_missing_gap_s: float = 0.2

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
        if not 0 < self.kickoff_centre_radius_m < self.kickoff_departure_m:
            raise ValueError("kickoff radii must satisfy 0 < centre < departure")
        if self.kickoff_control_window_s <= 0:
            raise ValueError("kickoff control window must be positive")
        if self.kickoff_max_missing_gap_s < 0:
            raise ValueError("kickoff missing gap must be nonnegative")


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


def _kickoff_context(events, n):
    """Only start-kickoff tags provide context; duplicates never add strength."""
    changes = np.zeros(n + 1, dtype=np.int64)
    normalise = lambda value: " ".join(str(value).casefold().split())
    for event in events:
        if normalise(event.get("code", "")) != "set pieces":
            continue
        kinds = {normalise(value) for key, value in (event.get("tags") or {}).items()
                 if normalise(key) == "type"}
        if kinds == {"kick off (start)"}:
            start, end = max(0, event["start_frame"]), min(n, event["end_frame"])
            if start >= end:
                continue
            changes[start] += 1
            changes[end] -= 1
    return np.cumsum(changes[:-1]) > 0


def _kickoff_flags(match, control, settings, usable, still, moving, totals=None):
    """A separate geometric episode, never generic live evidence or final labels.

    Missing frames pause observed support within a total per-confirmation budget.
    Bounded cross-gap displacement checks reacquisition; it never fills positions.
    Control at either endpoint suffices. Reception may confirm after motion ends.
    """
    n = len(match.frame)
    result = np.zeros(n, dtype=bool)
    context = _kickoff_context(match.events, n)
    centre = np.asarray(match.pitch_m) / 2
    offset = match.ball_xy_m - centre
    radius = np.hypot(offset[:, 0], offset[:, 1])
    settle_frames = max(1, math.ceil(settings.stop_duration_s * match.fps))
    motion_frames = max(1, math.ceil(settings.motion_duration_s * match.fps))
    gap_frames = math.floor(settings.kickoff_max_missing_gap_s * match.fps)
    control_frames = math.ceil(settings.kickoff_control_window_s * match.fps)
    context_frames = math.ceil(settings.restart_context_s * match.fps)
    previous_half = 0
    settled = count = missing = 0
    origin = armed_at = onset = last_control = last_observed = last_motion = None
    for i in range(n):
        half = int(match.half[i])
        counters = None
        if totals is not None and half:
            counters = totals.setdefault(str(half), dict.fromkeys((
                "context_frames", "observed_context_frames", "usable_context_frames",
                "centre_observed_context_frames", "centre_usable_context_frames",
                "centre_slow_frames", "settlement_confirmations",
                "moving_after_settlement_frames", "motion_dwell_frames",
                "departure_frames", "control_corroborated_departure_frames",
                "candidate_pulses", "missing_budget_resets", "rejected_observation_resets",
                "episode_expiry_resets", "context_loss_resets", "motion_support_resets",
                "blocked_by_confirmed_stop", "confirmed_kickoffs"), 0))
            if half == previous_half and not context[i] and (settled or armed_at is not None):
                counters["context_loss_resets"] += 1
        if half != previous_half or not half or not context[i]:
            settled = count = missing = 0
            origin = armed_at = onset = last_control = last_observed = last_motion = None
        previous_half = half
        if not half or not context[i]:
            continue
        if counters is not None:
            counters["context_frames"] += 1
        if not match.ball_observed[i]:
            missing += 1
            if missing > gap_frames:
                if counters is not None and (settled or armed_at is not None):
                    counters["missing_budget_resets"] += 1
                settled = count = 0
                origin = armed_at = onset = last_control = last_observed = last_motion = None
            continue

        if counters is not None:
            counters["observed_context_frames"] += 1
            counters["centre_observed_context_frames"] += bool(
                radius[i] <= settings.kickoff_centre_radius_m)

        in_pitch = np.all(match.ball_xy_m[i] >= 0) and np.all(
            match.ball_xy_m[i] <= np.asarray(match.pitch_m))
        valid, slow, fast = usable[i] and in_pitch, still[i], moving[i]
        if last_observed is not None and i > last_observed + 1:
            speed = (np.linalg.norm(match.ball_xy_m[i] - match.ball_xy_m[last_observed])
                     * match.fps / (i - last_observed))
            raw = match.ball_speed_mps
            supplied = raw is not None and np.isfinite(raw[i])
            # Cross-gap speed is only available inside the bounded missing budget.
            valid = (in_pitch and speed <= settings.max_ball_speed_mps
                     and (not supplied or raw[i] <= settings.max_ball_speed_mps))
            slow = valid and speed <= settings.stationary_speed_mps and (
                not supplied or raw[i] <= settings.stationary_speed_mps)
            fast = valid and speed >= settings.moving_speed_mps and (
                not supplied or raw[i] >= settings.moving_speed_mps)
        if not valid:
            if counters is not None:
                counters["rejected_observation_resets"] += bool(settled or armed_at is not None)
            settled = count = missing = 0
            origin = armed_at = onset = last_control = last_observed = last_motion = None
            continue
        if counters is not None:
            counters["usable_context_frames"] += 1
            counters["centre_usable_context_frames"] += bool(
                radius[i] <= settings.kickoff_centre_radius_m)
        last_observed = i
        if control[i]:
            last_control = i
        if slow and radius[i] <= settings.kickoff_centre_radius_m:
            if counters is not None:
                counters["centre_slow_frames"] += 1
            settled += 1
            count = 0
            onset = last_motion = None
            if settled >= settle_frames:
                if counters is not None and armed_at is None:
                    counters["settlement_confirmations"] += 1
                origin, armed_at = match.ball_xy_m[i].copy(), i
                missing = 0
            continue
        settled = 0
        if armed_at is None:
            missing = 0
            continue
        if i - armed_at > context_frames:
            if counters is not None:
                counters["episode_expiry_resets"] += 1
            origin = armed_at = onset = last_motion = None
            count = missing = 0
            continue
        if fast:
            if counters is not None:
                counters["moving_after_settlement_frames"] += 1
            if onset is None:
                onset = i
            count += 1
            last_motion = i
        elif count < motion_frames:
            if counters is not None and count:
                counters["motion_support_resets"] += 1
            count = 0
            onset = last_motion = None
        # A settled ball moved to another spot must not bank motion indefinitely.
        corroborated = (onset is not None and last_control is not None
                        and last_control >= onset - control_frames
                        and i - last_control <= control_frames)
        sustained = (count >= motion_frames and last_motion is not None
                     and i - last_motion <= control_frames)
        departed = (sustained and radius[i] > settings.kickoff_centre_radius_m
                    and np.linalg.norm(match.ball_xy_m[i] - origin) >= settings.kickoff_departure_m)
        if counters is not None:
            counters["motion_dwell_frames"] += bool(sustained)
            counters["departure_frames"] += bool(departed)
            counters["control_corroborated_departure_frames"] += bool(departed and corroborated)
        if departed and corroborated:
            if counters is not None:
                counters["candidate_pulses"] += 1
            result[i] = True
            settled = count = missing = 0
            origin = armed_at = onset = last_control = last_observed = last_motion = None
    return result


def _build_priors(match, features, config, totals=None, kickoff_totals=None):
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

    kickoff = _kickoff_flags(match, control, settings, usable, still, moving, kickoff_totals)

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
                # Only pending confirmation can bank support across gaps.
                # Confirmed stops retain the per-gap bound, not a lifetime budget.
                if 0 < stop_run < stop_frames:
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
            stop_missing = 0
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

    # Do not issue an opening on a frame that also confirms a new stop (for
    # example control first appearing long after the ball settled at reception).
    blocked = kickoff & (out.dead_evidence > .5) & (out.dead_reliability > 0)
    kickoff &= ~blocked
    if kickoff_totals is not None:
        for half, counters in kickoff_totals.items():
            period = match.half == int(half)
            counters["blocked_by_confirmed_stop"] = int(np.count_nonzero(blocked & period))
            counters["confirmed_kickoffs"] = int(np.count_nonzero(kickoff & period))
    out.diagnostic_flags[kickoff] |= CONFIRMED_KICKOFF
    # Validate the complete result using the unchanged shared contract.
    return PriorData(out.dead_evidence, out.dead_reliability, out.restart_evidence,
                     out.tag_team_evidence, out.tag_team_reliability,
                     out.diagnostic_flags)


def summarize_kickoff_diagnostics(match, features=None, config=None):
    """Local-only aggregate gate counts. Never returns frames or coordinates.

    Runs the actual detector with optional counters; no thresholds are changed.
    Stages identify the earliest unmet prerequisite, not a proven match cause.
    Keep reports from restricted inputs local, outside hosted tools and Git.
    """
    periods = {}
    _build_priors(match, features, config, kickoff_totals=periods)
    settings = _section({} if config is None else config, "dead_ball", DeadBallConfig)
    enabled = settings.enabled and settings.evidence_weight > 0
    # Diagnostic-only lookback: did existing still-centre evidence occur just
    # before a tag window? It never arms or alters the actual detector.
    context = _kickoff_context(match.events, len(match.frame))
    starts = np.flatnonzero(context & ~np.r_[False, context[:-1]]) if len(context) else []
    changes = np.zeros(len(match.frame) + 1, dtype=np.int64)
    lookback = math.ceil(settings.restart_context_s * match.fps)
    for start in starts:
        changes[max(0, start-lookback)] += 1
        changes[start] -= 1
    before_tag = (np.cumsum(changes[:-1]) > 0) & ~context
    _, slow, _, _ = _motion(match, settings)
    offset = match.ball_xy_m - np.asarray(match.pitch_m)/2
    near_centre = np.hypot(offset[:, 0], offset[:, 1]) <= settings.kickoff_centre_radius_m
    for half, counters in periods.items():
        counters["slow_centre_before_tag_frames"] = int(np.count_nonzero(
            before_tag & slow & near_centre & (match.half == int(half))))
        stages = (
            ("context_frames", "NO_START_TAG_CONTEXT"),
            ("usable_context_frames", "NO_USABLE_BALL_IN_CONTEXT"),
            ("settlement_confirmations", "NO_CONFIRMED_CENTRE_SETTLEMENT"),
            ("motion_dwell_frames", "NO_SUSTAINED_MOTION_AFTER_SETTLEMENT"),
            ("departure_frames", "NO_CONFIRMED_DEPARTURE"),
            ("control_corroborated_departure_frames", "NO_ENDPOINT_CONTROL"),
            ("confirmed_kickoffs", "BLOCKED_BY_CONFIRMED_STOP"),
        )
        counters["stage"] = next((reason for field, reason in stages if not counters[field]),
                                 "ONE_CONFIRMATION" if counters["confirmed_kickoffs"] == 1
                                 else "MULTIPLE_CONFIRMATIONS")
        if counters["stage"] == "NO_CONFIRMED_CENTRE_SETTLEMENT":
            if not counters["centre_slow_frames"] and counters["slow_centre_before_tag_frames"]:
                detail = "SLOW_CENTRE_SEEN_BEFORE_TAG"
            elif not counters["centre_observed_context_frames"]:
                detail = "NO_CENTRE_OBSERVATION_IN_TAG"
            elif not counters["centre_usable_context_frames"]:
                detail = "NO_USABLE_CENTRE_OBSERVATION"
            elif not counters["centre_slow_frames"]:
                detail = "CENTRE_OBSERVATIONS_FAIL_STILLNESS"
            else:
                detail = "FRAGMENTED_SETTLEMENT_SUPPORT"
            counters["settlement_detail"] = detail
    return {"enabled": enabled, "periods": periods}


def summarize_kickoff_coverage(match, check_frame, config=None):
    """Human-only coverage check; the check frame is never used by inference.

    Returns local aggregate counts and categories, no positions or frame IDs.
    The surrounding window reuses restart_context_s solely for diagnostics.
    A missing observation at the check does not prove the kick was unobserved.
    """
    _validate_inputs(match, None)
    if (isinstance(check_frame, bool) or not isinstance(check_frame, (int, np.integer))
            or not 0 <= check_frame < len(match.frame) or match.half[check_frame] == 0):
        raise ValueError("check frame must be an integer inside a graded period")
    settings = _section({} if config is None else config, "dead_ball", DeadBallConfig)
    context = _kickoff_context(match.events, len(match.frame))
    half = match.half[check_frame]
    period_start, period_end = int(check_frame), int(check_frame) + 1
    while period_start > 0 and match.half[period_start-1] == half:
        period_start -= 1
    while period_end < len(match.frame) and match.half[period_end] == half:
        period_end += 1
    offset = match.ball_xy_m - np.asarray(match.pitch_m)/2
    near = match.ball_observed & (
        np.hypot(offset[:, 0], offset[:, 1]) <= settings.kickoff_centre_radius_m)
    _, slow, _, _ = _motion(match, settings)
    # Find the beginning of the connected tag window that covers the check.
    tag_start = int(check_frame)
    if context[check_frame]:
        while tag_start > period_start and context[tag_start-1]:
            tag_start -= 1
        before_tag = slice(period_start, tag_start)
        if np.any(near[before_tag] & slow[before_tag]):
            pre_tag = "SLOW_CENTRE_OBSERVED_BEFORE_TAG"
        elif np.any(near[before_tag]):
            pre_tag = "CENTRE_OBSERVED_BEFORE_TAG"
        else:
            pre_tag = "NO_CENTRE_OBSERVATION_BEFORE_TAG"
    else:
        before_tag = slice(period_start, period_start)
        pre_tag = "CHECK_NOT_IN_START_TAG"
    radius_frames = math.ceil(settings.restart_context_s * match.fps)
    window = slice(max(period_start, check_frame-radius_frames),
                   min(period_end, check_frame+radius_frames+1))
    observed = int(np.count_nonzero(match.ball_observed[window]))
    near_count = int(np.count_nonzero(near[window]))
    if not observed:
        window_category = "BALL_MISSING_THROUGH_CHECK_WINDOW"
    elif near_count:
        window_category = "CENTRE_OBSERVED_IN_CHECK_WINDOW"
    else:
        window_category = "BALL_OBSERVED_AWAY_FROM_CENTRE_IN_CHECK_WINDOW"
    return {
        "tag_coverage": "TAG_COVERS_CHECK" if context[check_frame] else "TAG_MISSES_CHECK",
        "pre_tag_centre": pre_tag,
        "check_observation": "BALL_OBSERVED_AT_CHECK" if match.ball_observed[check_frame]
        else "BALL_MISSING_AT_CHECK",
        "window_observation": window_category,
        "counts": {
            "observed_in_check_window": observed,
            "centre_observed_in_check_window": near_count,
            "centre_observed_before_tag": int(np.count_nonzero(near[before_tag])),
            "slow_centre_before_tag": int(np.count_nonzero(near[before_tag] & slow[before_tag])),
        },
    }


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
    totals["confirmed_kickoffs"] = int(np.count_nonzero(
        priors.diagnostic_flags & CONFIRMED_KICKOFF))
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
        # Structural invariant check, not an observed attrition mechanism:
        # validated stationary/moving thresholds make the two gates disjoint.
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
