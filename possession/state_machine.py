"""E2's module: turn per-frame evidence into a stable H/A/D/X sequence.

This is the temporal layer described in docs/team/INTERFACES.md ("State owner output"):

    decode(match, features, priors, config) -> Prediction

`match`, `features` and `priors` are duck-typed on purpose. E1's MatchData and E4's/E3's
FeatureData/PriorData do not exist yet (see TEAM_PLAN.md), so this module only reads the
attributes INTERFACES.md already promises will exist on them -- `match.frame`, `match.half`,
`features.team_evidence`, `features.team_reliability`, `priors.dead_evidence`,
`priors.dead_reliability`, `priors.restart_evidence`, `priors.tag_team_evidence`,
`priors.tag_team_reliability` -- rather than importing a concrete type. Any object exposing
those (the real contracts, or a tests fixture) works unchanged.

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
"""

from dataclasses import dataclass, field
from typing import List

import numpy as np

# Params
H, A, D, X = "H", "A", "D", "X"


@dataclass(frozen=True)
class StateMachineConfig:
    """All thresholds in human units (seconds, [0,1] scores). See Decision 4 in the design doc:
    the dwell lengths are a real, quantified latency cost (EVALUATION.md's "N frames late" table),
    not a free safety margin -- treat these as something to revisit, not fixed constants.
    """

    fps: float = 25.0

    # Hysteresis: occurrences (not necessarily consecutive, see Decision 3) a candidate needs
    # before the state actually switches.
    dead_dwell_s: float = 0.32   # ~8 frames -- stoppages tend to be announced cleanly
    team_dwell_s: float = 0.60   # ~15 frames -- a turnover should need more than a touch

    # Dead/alive decision.
    dead_threshold: float = 0.6        # priors.dead_evidence needed to call a frame "dead"
    dead_reliability_min: float = 0.3  # below this, dead_evidence is treated as not informative
    restart_weight: float = 0.5        # restart_evidence counts against calling a frame dead

    # Team decision (H vs A), after fusing features.team_evidence and priors.tag_team_evidence.
    team_margin_threshold: float = 0.15   # required |evidence[H] - evidence[A]| to be decisive
    team_reliability_min: float = 0.25    # combined reliability floor to trust that margin

    @property
    def dead_dwell_frames(self) -> int:
        return max(1, round(self.dead_dwell_s * self.fps))

    @property
    def team_dwell_frames(self) -> int:
        return max(1, round(self.team_dwell_s * self.fps))


@dataclass
class Transition:
    """One state change, for diagnostics and tests -- not part of the scored output."""

    frame: int
    from_state: str
    to_state: str
    reason: str


@dataclass
class Prediction:
    """decode()'s return value. `labels` is the only field the scorer ever sees."""

    labels: np.ndarray                       # object array of "H"/"A"/"D"/"X", shape [N]
    transitions: List[Transition] = field(default_factory=list)


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


def decode(match, features, priors, config: StateMachineConfig = None) -> Prediction:
    """The whole state machine. See the module docstring and the decision doc for the rationale.

    `match.half` is 0 for ungraded frames (before kickoff, halftime, after the final whistle),
    and the half number (1 or 2) otherwise -- the convention docs/team/INTERFACES.md specifies.
    """
    config = config or StateMachineConfig()
    half = np.asarray(match.half)
    n = len(half)

    candidate = _decisive_state_per_frame(features, priors, config)

    labels = np.full(n, X, dtype=object)
    transitions: List[Transition] = []

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

        required = config.dead_dwell_frames if this_candidate == D else config.team_dwell_frames
        if pending_count >= required:
            transitions.append(Transition(
                frame=int(match.frame[i]) if hasattr(match, "frame") else i,
                from_state=current_state, to_state=this_candidate,
                reason="{} decisive occurrences for the new candidate".format(pending_count),
            ))
            current_state = this_candidate
            pending_state, pending_count = None, 0

        labels[i] = current_state

    return Prediction(labels=labels, transitions=transitions)
