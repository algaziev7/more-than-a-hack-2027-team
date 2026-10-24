"""Version 1 array contracts. Team evidence columns are always ordered H, A.

Constructors validate without changing caller-owned arrays. Missing coordinates
are NaN pairs, never zero. No contract contains or loads ground truth.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import numpy as np

SCHEMA_VERSION = 1
LABELS = ("H", "A", "D", "X")


class Event(TypedDict):
    start_frame: int
    end_frame: int
    start_s: float
    end_s: float
    code: str
    tags: Dict[str, str]


def _array(name, value, shape, kind):
    if not isinstance(value, np.ndarray) or value.shape != shape:
        raise ValueError(f"{name} must be a numpy array with shape {shape}")
    if value.dtype.kind not in kind:
        raise ValueError(f"{name} has an invalid dtype")


def validate_frame(frame):
    """Require the exact row axis, including dtype and every intermediate ID."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 1:
        raise ValueError("frame must be a one-dimensional numpy array")
    if frame.dtype != np.dtype("int64"):
        raise ValueError("frame must have dtype int64")
    if not np.array_equal(frame, np.arange(len(frame), dtype=np.int64)):
        raise ValueError("frame must be exactly 0..N-1 in order")
    return len(frame)


def _positions(name, xy, observed, shape):
    _array(name, xy, shape + (2,), "f")
    _array(name + " observation mask", observed, shape, "b")
    finite = np.isfinite(xy).all(axis=-1)
    missing = np.isnan(xy).all(axis=-1)
    if not np.all(finite | missing):
        raise ValueError(f"{name} must contain finite pairs or NaN pairs")
    if not np.array_equal(finite, observed):
        raise ValueError(f"{name} observation mask disagrees with coordinates")


def _unit(name, value, shape):
    _array(name, value, shape, "f")
    if not np.all(np.isfinite(value) & (value >= 0) & (value <= 1)):
        raise ValueError(f"{name} must be finite and in [0,1]")


def _team_evidence(name, evidence, reliability, n):
    _unit(name, evidence, (n, 2))
    _unit(name + " reliability", reliability, (n,))
    if not np.allclose(evidence.sum(axis=1), 1, rtol=0, atol=1e-7):
        raise ValueError(f"{name} rows must sum to one in H,A order")
    if not np.allclose(evidence[reliability == 0], 0.5, rtol=0, atol=1e-7):
        raise ValueError(f"{name} must be neutral where reliability is zero")


@dataclass
class MatchData:
    frame: np.ndarray
    half: np.ndarray
    fps: float
    pitch_m: Tuple[float, float]
    ball_xy_m: np.ndarray
    ball_observed: np.ndarray
    players_xy_m: np.ndarray
    player_observed: np.ndarray
    slot_team: np.ndarray
    ball_speed_mps: Optional[np.ndarray] = None
    events: List[Event] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self):
        n = validate_frame(self.frame)
        _array("half", self.half, (n,), "i")
        if self.half.dtype != np.dtype("int8") or not np.isin(self.half, [0, 1, 2]).all():
            raise ValueError("half must have dtype int8 and contain only 0,1,2")
        if isinstance(self.fps, bool) or not np.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("fps must be finite and positive")
        if len(self.pitch_m) != 2 or not all(np.isfinite(v) and v > 0 for v in self.pitch_m):
            raise ValueError("pitch_m must contain two finite positive dimensions")
        if not isinstance(self.slot_team, np.ndarray) or self.slot_team.ndim != 1:
            raise ValueError("slot_team must be a one-dimensional numpy array")
        if not np.isin(self.slot_team, ["H", "A"]).all():
            raise ValueError("slot_team contains an unknown team")
        p = len(self.slot_team)
        if p == 0:
            raise ValueError("at least one track slot is required")
        _positions("ball_xy_m", self.ball_xy_m, self.ball_observed, (n,))
        _positions("players_xy_m", self.players_xy_m, self.player_observed, (n, p))
        if self.ball_speed_mps is not None:
            _array("ball_speed_mps", self.ball_speed_mps, (n,), "f")
            speed = self.ball_speed_mps
            if not np.all(np.isnan(speed) | (np.isfinite(speed) & (speed >= 0))):
                raise ValueError("ball_speed_mps must be nonnegative or NaN")
            if np.any(np.isfinite(speed) & ~self.ball_observed):
                raise ValueError("ball speed cannot be observed without a ball position")
        for event in self.events:
            start, end = event["start_frame"], event["end_frame"]
            if any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) for v in (start, end)):
                raise ValueError("event frame boundaries must be integers")
            if not 0 <= start < end <= n:
                raise ValueError("events must be nonempty half-open intervals clipped to [0,N]")
            if not isinstance(event["tags"], dict) or not isinstance(event["code"], str):
                raise ValueError("events require a code string and original tag dictionary")


@dataclass
class FeatureData:
    frame: np.ndarray
    features: Dict[str, np.ndarray]
    validity: Dict[str, np.ndarray]
    team_evidence: np.ndarray
    team_reliability: np.ndarray

    def __post_init__(self):
        n = validate_frame(self.frame)
        if self.features.keys() != self.validity.keys():
            raise ValueError("every feature must have exactly one validity mask")
        for name, value in self.features.items():
            _array(name, value, (n,), "f")
            _array(name + " validity", self.validity[name], (n,), "b")
            if not np.isfinite(value[self.validity[name]]).all():
                raise ValueError(f"{name} is nonfinite on valid frames")
        _team_evidence("team_evidence", self.team_evidence, self.team_reliability, n)


@dataclass
class PriorData:
    dead_evidence: np.ndarray
    dead_reliability: np.ndarray
    restart_evidence: np.ndarray
    tag_team_evidence: np.ndarray
    tag_team_reliability: np.ndarray
    diagnostic_flags: Optional[np.ndarray] = None

    def __post_init__(self):
        if not isinstance(self.dead_evidence, np.ndarray) or self.dead_evidence.ndim != 1:
            raise ValueError("dead_evidence must be a one-dimensional numpy array")
        n = len(self.dead_evidence)
        for name in ("dead_evidence", "dead_reliability", "restart_evidence"):
            _unit(name, getattr(self, name), (n,))
        if not np.allclose(self.dead_evidence[self.dead_reliability == 0], 0.5):
            raise ValueError("dead evidence must be neutral where reliability is zero")
        _team_evidence("tag_team_evidence", self.tag_team_evidence, self.tag_team_reliability, n)
        if self.diagnostic_flags is not None:
            _array("diagnostic_flags", self.diagnostic_flags, (n,), "iu")


@dataclass
class Prediction:
    labels: np.ndarray
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self):
        if not isinstance(self.labels, np.ndarray) or self.labels.ndim != 1:
            raise ValueError("labels must be a one-dimensional numpy array")
        if not np.isin(self.labels, LABELS).all():
            raise ValueError("labels must contain only H/A/D/X")
