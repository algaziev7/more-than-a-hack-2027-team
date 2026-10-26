"""Convert automatic event intervals into evidence, never final possession labels.

The list-based helpers use only the standard library; the PriorData adapters
use the team's existing NumPy dependency. Inputs use dictionaries returned by
starter.load_smart_tagging.load. All intervals are [start_frame, end_frame).
See docs/team/TAGGING.md for the state-machine integration contract.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import math
from numbers import Real
import operator
from typing import Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from possession.contracts import PriorData


# Conservative allowlist: ambiguous/defensive phases and goals are left neutral.
ATTACKING_CODES = frozenset({
    "build up", "progression", "attacking transition", "creating chances",
    "ball in final third", "ball in the box", "long ball",
})
TEAM_ALIASES = {
    "barcelona": "H", "fc barcelona": "H",
    "atletic club": "A", "athletic club": "A",
}

# Per-frame diagnostic_flags bitmask; several flags can be set together.
TEAM_CONFLICT = 1
UNKNOWN_TEAM = 2
RESTART_WINDOW = 4


@dataclass(frozen=True)
class TaggingConfig:
    """Heuristic weights, not fitted probabilities or measured confidence."""

    team_reliability: float = 0.5
    restart_strength: float = 0.5

    def __post_init__(self):
        for name in ("team_reliability", "restart_strength"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, Real)
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("{} must be a finite number in [0, 1]".format(name))


@dataclass
class TaggingSignals:
    """Aligned Python lists; team columns are always (H, A).

    These are the tagging-only fields of the proposed PriorData contract.
    dead_* stays neutral until a separate dead-ball model supplies evidence.
    Consumers can convert the lists using numpy.asarray in their own pipeline.
    """

    frame: List[int]
    tag_team_evidence: List[Tuple[float, float]]
    tag_team_reliability: List[float]
    restart_evidence: List[float]
    dead_evidence: List[float]
    dead_reliability: List[float]
    diagnostic_flags: List[int]


def _normalise(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("event codes, tag keys, and tag values must be strings or None")
    return " ".join(value.split()).casefold()


def _integer(value, name):
    if isinstance(value, bool):
        raise ValueError("{} must be an integer, not a boolean".format(name))
    try:
        return operator.index(value)
    except TypeError:
        raise ValueError("{} must be an integer".format(name)) from None


def build_tagging_signals(
    events: Iterable[Dict],
    n_frames: int,
    config: Optional[TaggingConfig] = None,
) -> TaggingSignals:
    """Build N aligned clues from already frame-indexed event dictionaries.

    Duplicate or overlapping same-team events do not increase reliability.
    Opposing attacking tags cancel to neutral where they overlap. SET PIECES
    creates a restart-window clue but no live-team or dead-ball prediction,
    even when its team is known. Unknown teams cannot create a team preference.

    Missing tags are allowed; malformed frame indices or reversed intervals
    raise ValueError. Bounds are clipped to the recording; empty spans vanish.
    Events are not mutated. Complexity is O(N + number of events).
    """
    n_frames = _integer(n_frames, "n_frames")
    if n_frames < 0:
        raise ValueError("n_frames must be nonnegative")
    if config is None:
        config = TaggingConfig()
    if not isinstance(config, TaggingConfig):
        raise TypeError("config must be a TaggingConfig")

    # Difference arrays count coverage, not independent votes/confidence.
    changes = {key: [0] * (n_frames + 1) for key in ("H", "A", "restart", "unknown")}
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise ValueError("event {} must be a mapping".format(index))
        try:
            start = _integer(event["start_frame"], "start_frame")
            end = _integer(event["end_frame"], "end_frame")
            if end < start:
                raise ValueError("end_frame must not precede start_frame")
            code = _normalise(event.get("code"))
            tags = event.get("tags")
            if tags is None:
                tags = {}
            if not isinstance(tags, Mapping):
                raise ValueError("tags must be a mapping or None")
            # Treat conflicting case variants of Team as unresolved, not last-wins.
            teams = {TEAM_ALIASES.get(_normalise(value))
                     for key, value in tags.items() if _normalise(key) == "team"}
            team = next(iter(teams)) if len(teams) == 1 else None
        except (KeyError, ValueError) as exc:
            raise ValueError("event {}: {}".format(index, exc)) from None

        start, end = max(0, start), min(n_frames, end)
        if start >= end:
            continue
        channels = []
        if code == "set pieces":
            channels.append("restart")
        elif code in ATTACKING_CODES and team is not None:
            channels.append(team)
        if (code == "set pieces" or code in ATTACKING_CODES) and team is None:
            channels.append("unknown")
        for channel in channels:
            changes[channel][start] += 1
            changes[channel][end] -= 1

    out = TaggingSignals(
        frame=list(range(n_frames)),
        tag_team_evidence=[(0.5, 0.5)] * n_frames,
        tag_team_reliability=[0.0] * n_frames,
        restart_evidence=[0.0] * n_frames,
        dead_evidence=[0.5] * n_frames,
        dead_reliability=[0.0] * n_frames,
        diagnostic_flags=[0] * n_frames,
    )
    active = dict.fromkeys(changes, 0)
    for frame in range(n_frames):
        for channel in changes:
            active[channel] += changes[channel][frame]
        home, away = active["H"] > 0, active["A"] > 0
        if home and away:
            out.diagnostic_flags[frame] |= TEAM_CONFLICT
        elif (home or away) and config.team_reliability > 0:
            out.tag_team_evidence[frame] = (1.0, 0.0) if home else (0.0, 1.0)
            out.tag_team_reliability[frame] = float(config.team_reliability)
        if active["restart"]:
            out.restart_evidence[frame] = float(config.restart_strength)
            out.diagnostic_flags[frame] |= RESTART_WINDOW
        if active["unknown"]:
            out.diagnostic_flags[frame] |= UNKNOWN_TEAM
    return out


def load_tagging_signals(data_dir=None, game=None, config=None) -> TaggingSignals:
    """Read the tactical XML through the existing loader, without printing data.

    Uses MTAH_DATA_DIR when data_dir is omitted. Requires only the tagging XML,
    not tracking, video, homography, or ground truth. Length comes from games.py.
    """
    from games import GAME, source_frames
    from starter.load_smart_tagging import load

    game = GAME if game is None else game
    return build_tagging_signals(
        load(game=game, data_dir=data_dir),
        n_frames=source_frames(game=game),
        config=config,
    )


def to_prior_data(signals: TaggingSignals) -> "PriorData":
    """Copy tagging lists into Azamat's validated NumPy-based PriorData.

    NumPy is imported only when this adapter is called. The original signal
    builders keep working with the standard library alone. No clue is reweighted
    or filtered, and no input is changed. The decoder still handles half masks.
    """
    import numpy as np
    from possession.contracts import PriorData

    if not isinstance(signals, TaggingSignals):
        raise TypeError("signals must be a TaggingSignals")
    n = len(signals.frame)
    for index, frame in enumerate(signals.frame):
        if _integer(frame, "frame") != index:
            raise ValueError("frame must be exactly 0..N-1 in order")

    # PriorData has no frame field and infers N from dead_evidence. Check that
    # against the source timeline rather than accepting equally truncated lists.
    if len(signals.dead_evidence) != n:
        raise ValueError("dead_evidence length must match frame")

    values = {
        name: np.array(getattr(signals, name), dtype=np.float64, copy=True)
        for name in ("dead_evidence", "dead_reliability", "restart_evidence",
                     "tag_team_evidence", "tag_team_reliability")
    }
    if n == 0 and values["tag_team_evidence"].shape == (0,):
        values["tag_team_evidence"] = values["tag_team_evidence"].reshape(0, 2)

    # Do not silently turn fractional or boolean reason codes into integers.
    flags = np.array(signals.diagnostic_flags, copy=True)
    if n == 0 and flags.shape == (0,):
        flags = np.empty(0, dtype=np.int64)
    if flags.dtype.kind not in "iu":
        raise ValueError("diagnostic_flags must contain integers")

    # The shared constructor checks all lengths, shapes, values, and neutral
    # evidence on frames whose reliability is zero.
    return PriorData(**values, diagnostic_flags=flags)


def build_tagging_priors(
    events: Iterable[Dict],
    n_frames: int,
    config: Optional[TaggingConfig] = None,
) -> "PriorData":
    """Build tagging-only PriorData directly from already loaded events.

    Use build_tagging_priors(match.events, len(match.frame)) after load_match.
    Dead-ball evidence remains neutral; motion-based stoppage detection is
    separate future work. Requires the existing team's NumPy dependency.
    """
    return to_prior_data(build_tagging_signals(events, n_frames, config))
