"""E2's module: turn per-frame evidence into a stable H/A/D/X sequence.

This is the temporal layer described in docs/team/INTERFACES.md ("State owner output"):

    decode(match, features, priors, config) -> Prediction

`match`/`features`/`priors` are read duck-typed (`match.frame`, `match.half`,
`features.team_evidence`, `features.team_reliability`, `priors.dead_evidence`,
`priors.dead_reliability`, `priors.restart_evidence`, `priors.tag_team_evidence`,
`priors.tag_team_reliability`) rather than type-checked against `possession.contracts`. Azamat's
`MatchData`/`FeatureData` and Almaz's `PriorData` now exist and are the real types this is meant
to consume (see `possession.data.load_match`, `possession.dead_ball.build_priors`), but this
module doesn't import or isinstance-check them, so it also runs unchanged against the lighter
`tests.fixtures`-style objects used in `tests/test_state_machine.py`. `Prediction` *is* imported
from `possession.contracts`, since that return type is this module's own contract to satisfy.

Design rationale, and the review that shaped it, are written up in full in
docs/team/decisions/2026-10-23-e2-data-evidence-and-state-machine-design.md. Summary:

- Evidence is a (value, reliability) pair, never a hard per-frame guess (see Decision 1 there).
- This is a hysteresis state machine, not a per-frame classifier smoothed afterwards: a candidate
  state must win for `dwell_frames` *occurrences* before the state actually switches.
- Dead and team transitions get separate dwell lengths (dead shorter -- stoppages are often
  announced cleanly; team changes need more sustained proof).
- Every half starts in D. Correct for the second half (graded before its own kickoff); merely
  harmless for the first (graded live from kickoff) -- see Decision 2.
- A frame with no decisive candidate (ball missing, nothing reliable) PAUSES the dwell count, it
  does not reset it. This is Decision 3, found on review before any code existed: resetting on a
  neutral frame is fragile exactly where it matters most, since the ball is missing on 41% of
  graded frames and in clusters, not as isolated frames -- a real transition could have its count
  wiped every frame of an overlapping occlusion and never be detected.
- `X` is reserved for genuinely ungraded frames (`half == 0`). Every graded frame gets a concrete
  call, so spell boundaries stay well-defined. No ML, no vectorization yet -- see the decision
  doc's "explicitly deferred" list for why.
- `dead_dwell_s` is deliberately short (Decision 5). Almaz's `possession.dead_ball.build_priors`
  already waits ~0.6s of sustained stillness before it confirms a stop (see DEAD_BALL.md), and
  INTERFACES.md says explicitly: "confirmation already adds a delay, so E2 should account for it
  before adding further persistence." Stacking a second long dwell on top would double-delay
  every dead-ball call for no benefit; a short one is still kept as a margin against a single
  noisy frame, not as a second confirmation window.

`config` follows the same convention as `dead_ball.DeadBallConfig` / `tagging.TaggingConfig`: the
caller passes the *whole* shared pipeline dict, and this module reads only its own
`config["state_machine"]` section, so Goblin's pipeline can pass one config object to every stage.
"""

from dataclasses import dataclass, fields, replace
from numbers import Real
import math

import numpy as np

from possession.contracts import Prediction

# Params
H, A, D, X = "H", "A", "D", "X"


@dataclass(frozen=True)
class StateMachineConfig:
    """All thresholds in human units (seconds, [0,1] scores). See Decision 4 in the design doc:
    the dwell lengths are a real, quantified latency cost (EVALUATION.md's "N frames late" table),
    not a free safety margin -- treat these as something to revisit, not fixed constants.
    """

    # decode uses match.fps. Kept as a fallback for legacy lightweight fixtures;
    # an explicit config fps must agree with a match that supplies its own fps.
    fps: float = 25.0

    # Hysteresis: occurrences (not necessarily consecutive, see Decision 3) a candidate needs
    # before the state actually switches.
    dead_dwell_s: float = 0.08   # ~2 frames -- Almaz's prior already waits ~0.6s, see Decision 5
    team_dwell_s: float = 0.60   # ~15 frames -- a turnover should need more than a touch

    # Dead/alive decision.
    dead_threshold: float = 0.6        # priors.dead_evidence needed to call a frame "dead"
    dead_reliability_min: float = 0.3  # below this, dead_evidence is treated as not informative
    restart_weight: float = 0.5        # restart_evidence counts against calling a frame dead

    # Team decision (H vs A), after fusing features.team_evidence and priors.tag_team_evidence.
    team_margin_threshold: float = 0.15   # required |evidence[H] - evidence[A]| to be decisive
    team_reliability_min: float = 0.25    # combined reliability floor to trust that margin

    def __post_init__(self):
        for field_ in fields(self):
            value = getattr(self, field_.name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError("state_machine.{} must be a finite number".format(field_.name))
        if self.fps <= 0:
            raise ValueError("state_machine.fps must be positive")
        if min(self.dead_dwell_s, self.team_dwell_s) <= 0:
            raise ValueError("dwell durations must be positive")
        for name in ("dead_threshold", "dead_reliability_min", "restart_weight",
                     "team_margin_threshold", "team_reliability_min"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError("state_machine.{} must be in [0, 1]".format(name))

    @property
    def dead_dwell_frames(self) -> int:
        return max(1, math.ceil(self.dead_dwell_s * self.fps))

    @property
    def team_dwell_frames(self) -> int:
        return max(1, math.ceil(self.team_dwell_s * self.fps))


def _section(config, name, cls):
    """Pull this module's own section out of the shared pipeline config dict.

    Mirrors possession.dead_ball._section / possession.tagging.TaggingConfig's convention: the
    caller passes the whole pipeline dict, and each stage reads only its own named section, so
    Goblin's pipeline can hand the same config object to every stage.
    """
    config = {} if config is None else config
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    options = config.get(name, {})
    if not isinstance(options, dict):
        raise ValueError("{} settings must be an object".format(name))
    if set(options) - {field_.name for field_ in fields(cls)}:
        raise ValueError("unknown {} setting".format(name))
    return cls(**options)


def _combine(evidence_a, reliability_a, evidence_b, reliability_b):
    """Reliability-weighted average of two [0,1]-scored opinions about the same question.

    Neutral (0.5, reliability 0) when both inputs are unreliable, per the "no evidence => [0.5,
    0.5] / reliability 0" convention in docs/team/INTERFACES.md.
    """
    total = reliability_a + reliability_b
    safe_total = np.where(total > 0, total, 1.0)
    combined_evidence = np.where(
        total > 0,
        (evidence_a * reliability_a + evidence_b * reliability_b) / safe_total,
        0.5,
    )
    combined_reliability = np.minimum(1.0, total)
    return combined_evidence, combined_reliability


def _validate_alignment(match, features, priors, half):
    """Reject cross-module timeline mismatches before NumPy can broadcast them.

    Constructors validate each contract separately, not their joint length or
    alignment. Keep support for lightweight fixtures without imposing a second
    type/schema system; check only the arrays consumed here and available axes.
    """
    if half.ndim != 1:
        raise ValueError("match.half must be one-dimensional")
    n = len(half)
    if hasattr(match, "frame") and np.shape(match.frame) != (n,):
        raise ValueError("match.frame and match.half must use the same timeline")
    if hasattr(features, "frame"):
        if np.shape(features.frame) != (n,):
            raise ValueError("features.frame must match the match timeline length")
        if hasattr(match, "frame") and not np.array_equal(features.frame, match.frame):
            raise ValueError("features and match must use the same frame timeline")
    for owner, source, names in (
        ("features", features, ("team_evidence", "team_reliability")),
        ("priors", priors, ("dead_evidence", "dead_reliability", "restart_evidence",
                            "tag_team_evidence", "tag_team_reliability")),
    ):
        for name in names:
            expected = (n, 2) if name in ("team_evidence", "tag_team_evidence") else (n,)
            if np.shape(getattr(source, name)) != expected:
                raise ValueError("{}.{} must have shape {} on the match timeline".format(
                    owner, name, expected))


def _decisive_state_per_frame(features, priors, config: StateMachineConfig) -> np.ndarray:
    """One candidate per frame: H, A, D, or None (object dtype) -- "no decisive signal here".

    Dead/alive is checked before team identity: a confidently dead frame has no team to assign,
    and a stale team_evidence reading during a stoppage should not outvote a reliable dead signal.
    """
    n = len(priors.dead_evidence)
    candidate = np.full(n, None, dtype=object)

    effective_dead = np.clip(
        np.asarray(priors.dead_evidence, dtype=float)
        - config.restart_weight * np.asarray(priors.restart_evidence, dtype=float),
        0.0, 1.0,
    )
    dead_reliable = np.asarray(priors.dead_reliability, dtype=float) >= config.dead_reliability_min
    is_dead = dead_reliable & (effective_dead >= config.dead_threshold)
    candidate[is_dead] = D

    team_evidence, team_reliability = _combine(
        np.asarray(features.team_evidence, dtype=float)[:, 0],
        np.asarray(features.team_reliability, dtype=float),
        np.asarray(priors.tag_team_evidence, dtype=float)[:, 0],
        np.asarray(priors.tag_team_reliability, dtype=float),
    )
    margin = np.abs(team_evidence - 0.5) * 2.0  # evidence[H] - evidence[A], rescaled from [0,1]
    team_reliable = (~is_dead) & (team_reliability >= config.team_reliability_min) \
        & (margin >= config.team_margin_threshold)
    candidate[team_reliable & (team_evidence >= 0.5)] = H
    candidate[team_reliable & (team_evidence < 0.5)] = A
    return candidate


def decode(match, features, priors, config=None) -> Prediction:
    """The whole state machine. See the module docstring and the decision doc for the rationale.

    `match.half` is 0 for ungraded frames (before kickoff, halftime, after the final whistle),
    and the half number (1 or 2) otherwise -- the convention docs/team/INTERFACES.md specifies.

    `config` is the shared pipeline dict (see `_section`), e.g. `{"state_machine": {...}}`, not a
    `StateMachineConfig` directly -- matching how `dead_ball.build_priors` and
    `tagging.build_tagging_priors` take `config`.

    Dwell requires ceil(seconds * match.fps) supporting observations. Defaults
    at 25 fps are unchanged. An explicit legacy `state_machine.fps` must match
    `match.fps`; only lightweight inputs without fps use the config fallback.
    """
    settings = _section(config, "state_machine", StateMachineConfig)
    if hasattr(match, "fps"):
        if "fps" in (config or {}).get("state_machine", {}) and settings.fps != match.fps:
            raise ValueError("state_machine.fps must agree with match.fps")
        settings = replace(settings, fps=match.fps)
    half = np.asarray(match.half)
    _validate_alignment(match, features, priors, half)
    n = len(half)

    candidate = _decisive_state_per_frame(features, priors, settings)

    labels = np.full(n, X, dtype=object)
    transitions = []

    current_state = D
    pending_state = None
    pending_count = 0
    previous_half = 0

    for i in range(n):
        this_half = int(half[i])
        if this_half == 0:
            labels[i] = X
            previous_half = this_half
            continue

        if this_half != previous_half:
            # New half: no memory of the previous one survives. See the design doc's Decision 2
            # for why the reset target is D and why that's only *harmless*, not correct, at the
            # start of the first half.
            current_state = D
            pending_state = None
            pending_count = 0
        previous_half = this_half

        this_candidate = candidate[i]
        if this_candidate is None:
            # Decision 3: no decisive signal this frame -- pause the count, don't reset it. The
            # ball is missing on 41% of graded frames, in clusters; resetting here would make a
            # real transition's detection latency balloon with every occlusion it overlaps.
            labels[i] = current_state
            continue

        if this_candidate == current_state:
            pending_state, pending_count = None, 0
            labels[i] = current_state
            continue

        if this_candidate == pending_state:
            pending_count += 1
        else:
            pending_state, pending_count = this_candidate, 1

        required = settings.dead_dwell_frames if this_candidate == D else settings.team_dwell_frames
        if pending_count >= required:
            transitions.append({
                "frame": int(match.frame[i]) if hasattr(match, "frame") else i,
                "from_state": current_state, "to_state": this_candidate,
                "reason": "{} decisive occurrences for the new candidate".format(pending_count),
            })
            current_state = this_candidate
            pending_state, pending_count = None, 0

        labels[i] = current_state

    return Prediction(labels=labels, diagnostics={"transitions": transitions})
