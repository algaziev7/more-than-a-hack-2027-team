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
- Decision 6: once a stop has genuinely been confirmed, team evidence alone can no longer exit
  `D` -- it needs independent proof play actually resumed (reliable restart evidence, or E3's own
  live-motion confirmation). Found by Almaz: a player merely standing near the ball while waiting
  to take a throw-in, with the stop signal having simply gone quiet (not confirmed live), could
  otherwise read as "that player's team now has it." This keeps "is play live" and "who has it"
  as genuinely separate questions, per TEAM_PLAN.md. It never affects a `D` that's merely the
  half-start default (nothing has ever confirmed a stop), so an ordinary kickoff is unaffected.
  A safety valve (same decision, amended once the indefinite-freeze risk was demonstrated, not
  just theorized): sustained team evidence can still exit a latched `D`, but only after
  `latched_team_dwell_s` -- several times longer than an ordinary team change needs -- precisely
  because that length is what makes it categorically different from brief proximity.
- Decision 7: tracking and Smart Tagging team evidence are never averaged. Tracking whose
  reliability clears `team_reliability_min` decides the frame alone: decisive tracking votes,
  contested tracking (a duel) gives no candidate. Tags fill only frames where tracking is below
  that floor. `diagnostics["team_sources"]` counts graded frames decided each way.

`config` follows the same convention as `dead_ball.DeadBallConfig` / `tagging.TaggingConfig`: the
caller passes the *whole* shared pipeline dict, and this module reads only its own
`config["state_machine"]` section, so Goblin's pipeline can pass one config object to every stage.
"""

from collections import deque
from dataclasses import dataclass, fields, replace
from numbers import Real
import math

import numpy as np

from possession.contracts import Prediction
from possession.dead_ball import DeadBallConfig
from possession.tagging import TaggingConfig

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

    # Team decision (H vs A). Decision 7: each frame is decided by one source -- tracking if its
    # reliability clears the floor, otherwise the tag -- never an average of the two.
    team_margin_threshold: float = 0.15   # required |evidence[H] - evidence[A]| to be decisive
    team_reliability_min: float = 0.25    # a source's own reliability floor to trust that margin

    # Decision 6: once dead_confirmed is latched (a real stop was seen), team evidence alone
    # cannot exit D. One of these must also hold, on some frame since the stop was confirmed:
    #
    # restart_evidence_threshold must sit strictly ABOVE tagging.TaggingConfig.restart_strength
    # (default 0.5) and at or below dead_ball's CONFIRMED_RESTART pulse (0.75). A bare Smart
    # Tagging SET PIECES window sets restart_evidence to restart_strength for its *entire* span
    # (tagging.py), including every frame tagging/dead_ball jointly mark as a confirmed stop
    # (dead_ball.py's tagged_stop) -- at threshold 0.5 (`>=`), that bare hint alone would clear
    # the latch on the very same frame it gets set, making this decision a no-op for exactly the
    # tagged-stoppage case (a throw-in) it exists to fix. 0.6 is strictly above the bare hint and
    # below the confirmed pulse; decode() also validates this against the real tagging config
    # when given one, so the two can't silently drift back into collision.
    restart_evidence_threshold: float = 0.6
    live_confirmed_threshold: float = 0.3     # priors.dead_evidence this low (and reliable) counts
                                               # as E3's own confirmed live-motion signal (~0.1)

    # Safety valve: without this, the latch has no expiry at all. E3's own escape path (live-
    # motion or restart confirmation) needs a *usable* ball, and every unusable-ball frame also
    # wipes dead_ball's recent-stop context -- so a restart that happens to occur during an
    # occlusion (41% of graded frames, in clusters) could otherwise pin D indefinitely, even
    # against overwhelming team evidence. Demonstrated, not just theorized: 920 frames (~37s)
    # stuck in D in a synthetic repro before this field existed. Several times team_dwell_s on
    # purpose -- that length is what makes "sustained team evidence won" categorically different
    # from the brief proximity Decision 6 exists to ignore (Almaz's throw-in case).
    latched_team_dwell_s: float = 3.0   # ~75 frames

    # Bounded evidence age for ordinary (ungated) transitions: only supporting observations from
    # the last evidence_window_s count. Keeps Decision 3's tolerance for occlusions (a 100-frame
    # gap mid-turnover still works) without letting a touch from 40s ago combine with one now.
    evidence_window_s: float = 6.0   # ~150 frames

    def __post_init__(self):
        for field_ in fields(self):
            value = getattr(self, field_.name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError("state_machine.{} must be a finite number".format(field_.name))
        if self.fps <= 0:
            raise ValueError("state_machine.fps must be positive")
        if min(self.dead_dwell_s, self.team_dwell_s, self.latched_team_dwell_s) <= 0:
            raise ValueError("dwell durations must be positive")
        if self.latched_team_dwell_s <= self.team_dwell_s:
            raise ValueError("state_machine.latched_team_dwell_s must exceed team_dwell_s")
        if self.evidence_window_s < max(self.dead_dwell_s, self.team_dwell_s):
            raise ValueError("state_machine.evidence_window_s must be at least every dwell")
        for name in ("dead_threshold", "dead_reliability_min", "restart_weight",
                     "team_margin_threshold", "team_reliability_min",
                     "restart_evidence_threshold", "live_confirmed_threshold"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError("state_machine.{} must be in [0, 1]".format(name))
        # A frame that is both "dead" and "confirmed live" would set and clear the Decision 6
        # latch on the same frame, letting proximity alone exit a real stop (Beks's review).
        if self.live_confirmed_threshold >= self.dead_threshold:
            raise ValueError("state_machine.live_confirmed_threshold must be below dead_threshold")

    @property
    def dead_dwell_frames(self) -> int:
        return max(1, math.ceil(self.dead_dwell_s * self.fps))

    @property
    def team_dwell_frames(self) -> int:
        return max(1, math.ceil(self.team_dwell_s * self.fps))

    @property
    def latched_team_dwell_frames(self) -> int:
        return max(1, math.ceil(self.latched_team_dwell_s * self.fps))

    @property
    def evidence_window_frames(self) -> int:
        return max(1, math.ceil(self.evidence_window_s * self.fps))


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


def _team_call(evidence, reliability, config):
    """For one H/A source: (reliable, decisive, signed margin H - A) per frame.

    Subtract both columns so swapping teams negates the margin symmetrically. Allow only
    floating-point roundoff at an inclusive threshold; ties and zero-weight clues stay
    non-decisive even when configured floors are zero.
    """
    evidence = np.asarray(evidence, dtype=float)
    reliability = np.asarray(reliability, dtype=float)
    signed_margin = evidence[:, 0] - evidence[:, 1]
    margin = np.abs(signed_margin)
    roundoff = 8 * np.finfo(float).eps
    reliable = (reliability > 0) & (reliability >= config.team_reliability_min)
    decisive = reliable & (margin > roundoff) & (margin >= config.team_margin_threshold - roundoff)
    return reliable, decisive, signed_margin


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


def _decisive_state_per_frame(features, priors, config: StateMachineConfig):
    """One candidate per frame (H, A, D, or None), plus two per-frame booleans Decision 6 needs:
    `is_dead` (this frame alone looks confidently dead) and `exit_dead_ok` (this frame alone is
    positive proof play has resumed -- not merely the absence of a dead signal) -- and the masks
    of which team source decided each live frame, for diagnostics.

    Dead/alive is checked before team identity: a confidently dead frame has no team to assign,
    and a stale team_evidence reading during a stoppage should not outvote a reliable dead signal.
    """
    n = len(priors.dead_evidence)
    candidate = np.full(n, None, dtype=object)

    dead_evidence = np.asarray(priors.dead_evidence, dtype=float)
    restart_evidence = np.asarray(priors.restart_evidence, dtype=float)
    dead_weight = np.asarray(priors.dead_reliability, dtype=float)
    dead_reliable = (dead_weight > 0) & (dead_weight >= config.dead_reliability_min)

    effective_dead = np.clip(dead_evidence - config.restart_weight * restart_evidence, 0.0, 1.0)
    is_dead = dead_reliable & (effective_dead >= config.dead_threshold)
    candidate[is_dead] = D

    # Decision 6: proof play resumed, not just "no longer confirmed dead". live_confirmed is E3's
    # own confirmed-live-motion reading (dead_evidence reliably low); restart_confirmed is a
    # reliable restart clue (a tag window, or E3's CONFIRMED_RESTART pulse). Either is enough.
    live_confirmed = dead_reliable & (dead_evidence <= config.live_confirmed_threshold)
    restart_confirmed = restart_evidence >= config.restart_evidence_threshold
    # A frame still classified as dead after restart weighting cannot also
    # clear the stop latch. Resolve contradictory clues with dead precedence.
    exit_dead_ok = (~is_dead) & (live_confirmed | restart_confirmed)

    # Decision 7: tracking-first fusion. Reliable tracking owns the frame: decisive tracking
    # votes, contested tracking (a duel) gives no candidate, so a pending count pauses. Phase-level
    # tags span whole attacking windows and usually name the incumbent, so letting them fill a duel
    # -- or averaging them in -- cancels real turnovers. Tags fill only sub-floor tracking frames.
    track_reliable, track_decisive, track_margin = _team_call(
        features.team_evidence, features.team_reliability, config)
    _, tag_decisive, tag_margin = _team_call(
        priors.tag_team_evidence, priors.tag_team_reliability, config)
    use_tag = ~track_reliable & tag_decisive
    signed_margin = np.where(track_reliable, track_margin, tag_margin)
    team_decided = (~is_dead) & (track_decisive | use_tag)
    candidate[team_decided & (signed_margin > 0)] = H
    candidate[team_decided & (signed_margin < 0)] = A
    sources = {"tracking": (~is_dead) & track_decisive,
               "contested": (~is_dead) & track_reliable & ~track_decisive,
               "tag": (~is_dead) & use_tag}
    return candidate, is_dead, exit_dead_ok, sources


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
    # Distinct durations may still round to the same number of observations.
    # Check only after resolving match.fps, so low/high-rate inputs use their
    # actual dwell counts rather than the legacy 25-fps config fallback.
    if settings.latched_team_dwell_frames <= settings.team_dwell_frames:
        raise ValueError("state_machine.latched_team_dwell_s must require more frames "
                         "than team_dwell_s at the match fps")

    # Decision 6's restart_evidence_threshold must stay strictly above tagging's bare restart
    # hint, or team evidence could exit a confirmed stop using nothing but a SET PIECES tag
    # window -- the exact bug this decision was meant to fix. Checked here, against the real
    # tagging config if the caller supplied one (via the same _section helper tagging.py's own
    # build_tagging_priors uses, so a malformed section is rejected the same way, not with a
    # bare dict .get() that would raise the wrong exception type on bad input), so the two can't
    # silently drift back into collision (e.g. someone raising tagging.restart_strength without
    # noticing this coupling).
    tagging = _section(config, "tagging", TaggingConfig)
    tagging_restart_strength = tagging.restart_strength
    if settings.restart_evidence_threshold <= tagging_restart_strength:
        raise ValueError(
            "state_machine.restart_evidence_threshold ({}) must be strictly greater than "
            "tagging.restart_strength ({}), or a bare tag window alone could exit a confirmed "
            "stop".format(settings.restart_evidence_threshold, tagging_restart_strength))
    # dead_ball copies evidence_weight into dead_reliability, so a weight below this module's
    # floor would silently discard every stop and live confirmation. Disabling E3 is still fine.
    dead_ball = _section(config, "dead_ball", DeadBallConfig)
    if (dead_ball.enabled and 0 < dead_ball.evidence_weight
            and dead_ball.evidence_weight < settings.dead_reliability_min):
        raise ValueError(
            "dead_ball.evidence_weight ({}) is below state_machine.dead_reliability_min ({}), "
            "so every dead-ball clue would be ignored".format(
                dead_ball.evidence_weight, settings.dead_reliability_min))
    # Decision 7: each source must clear team_reliability_min alone, and every tag frame carries
    # tagging.team_reliability, so a lower non-zero weight would silently disable tag evidence.
    if 0 < tagging.team_reliability < settings.team_reliability_min:
        raise ValueError(
            "tagging.team_reliability ({}) is below state_machine.team_reliability_min ({}), "
            "so tag team evidence would never decide a frame".format(
                tagging.team_reliability, settings.team_reliability_min))

    half = np.asarray(match.half)
    _validate_alignment(match, features, priors, half)
    n = len(half)

    candidate, is_dead, exit_dead_ok, sources = _decisive_state_per_frame(
        features, priors, settings)

    labels = np.full(n, X, dtype=object)
    transitions = []

    current_state = D
    pending_state = None
    # Frame indices supporting pending_state, most recent at the right. A plain counter cannot
    # express the safety valve's "sustained," not just "many, however far apart" -- see below.
    pending_frames = deque()
    previous_half = 0
    # Decision 6: sticky across frames (not just "this exact frame"), so a brief dead confirmation
    # or a brief restart confirmation is remembered rather than needing to coincide with the exact
    # frame team evidence is trying to act on.
    dead_confirmed = False

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
            pending_state, pending_frames = None, deque()
            dead_confirmed = False
        previous_half = this_half

        if is_dead[i]:
            dead_confirmed = True
        elif exit_dead_ok[i] and pending_state == D:
            # Confirmed live play invalidates pending stop evidence: two isolated stop frames
            # separated by live play are not one stop. Keeps the current H/A label as-is.
            pending_state, pending_frames = None, deque()
        if exit_dead_ok[i] and dead_confirmed:
            dead_confirmed = False
            if pending_state in (H, A) and current_state == D:
                # The gate just lifted on a candidate that was actually subject to it. Discard
                # that progress (accumulated toward latched_team_dwell_frames) rather than
                # letting it carry over toward the now-applicable, much shorter
                # team_dwell_frames -- otherwise a long-accumulated "banked" run of mere
                # proximity could cash in the instant a single frame of real proof arrives,
                # which would undercut exactly what that proof is meant to require.
                #
                # The current_state == D guard matters: is_dead can latch dead_confirmed even
                # while current_state is already H/A (a lone dead-looking frame during live play
                # that never reached dead_dwell_frames) -- without this guard, a later
                # exit_dead_ok frame would wipe an ordinary, never-gated turnover's progress for
                # no reason. A pending D-candidate is never touched here either way -- entering D
                # was never gated by this latch, only leaving it.
                pending_state, pending_frames = None, deque()

        this_candidate = candidate[i]
        if this_candidate is None:
            # Decision 3: no decisive signal this frame -- pause the count, don't reset it. The
            # ball is missing on 41% of graded frames, in clusters; resetting here would make a
            # real transition's detection latency balloon with every occlusion it overlaps.
            labels[i] = current_state
            continue

        if this_candidate == current_state:
            pending_state, pending_frames = None, deque()
            labels[i] = current_state
            continue

        if this_candidate == pending_state:
            pending_frames.append(i)
        else:
            pending_state, pending_frames = this_candidate, deque([i])

        gated = this_candidate in (H, A) and current_state == D and dead_confirmed
        # Ordinary dwell: bounded evidence age (evidence_window_s), still tolerant of occlusions.
        window = settings.evidence_window_frames
        if gated:
            # The safety valve's whole justification is *sustained* evidence, categorically
            # different from brief proximity -- not "however many occurrences, however far
            # apart." Ordinary dwell tolerates gaps within evidence_window_s (the
            # ball can be missing a while mid-possession without doubt creeping in about who had
            # it), but a fixed per-gap bound can't express "sustained" either: any positive bound
            # still lets a long enough chain of just-under-the-bound gaps span an arbitrary total
            # span (this was tried and verified not to work before landing here). A genuine
            # sliding window does: only occurrences within the last `window` frames count, so the
            # count can never reflect more than `window` frames of real elapsed time.
            window = 2 * settings.latched_team_dwell_frames
        while pending_frames and i - pending_frames[0] > window:
            pending_frames.popleft()

        if this_candidate == D:
            required = settings.dead_dwell_frames
        elif gated:
            # Decision 6's safety valve: a confirmed stop needs independent proof it ended, but
            # team evidence alone can still override after much longer -- long enough to be
            # categorically different from the brief proximity Decision 6 exists to ignore, and
            # bounded so the latch can never pin D indefinitely if E3's own escape path can't
            # fire (e.g. a restart that happens to occur during an occlusion).
            required = settings.latched_team_dwell_frames
        else:
            required = settings.team_dwell_frames
        if len(pending_frames) >= required:
            transitions.append({
                "frame": int(match.frame[i]) if hasattr(match, "frame") else i,
                "from_state": current_state, "to_state": this_candidate,
                "reason": "{} decisive occurrences for the new candidate".format(len(pending_frames)),
            })
            if current_state == D and this_candidate != D:
                # Leaving D, whether via real proof or the safety valve -- don't carry a latch
                # into the live period that follows. Left set, a later stray is_dead frame would
                # have nothing to do (current_state isn't D), but a later exit_dead_ok frame
                # would still see dead_confirmed True from here and could wipe an unrelated,
                # never-gated turnover's progress, same failure mode as the guard just above.
                dead_confirmed = False
            current_state = this_candidate
            pending_state, pending_frames = None, deque()

        labels[i] = current_state

    graded = half > 0
    team_sources = {name: int(np.count_nonzero(mask & graded)) for name, mask in sources.items()}
    return Prediction(labels=labels, diagnostics={"transitions": transitions,
                                                  "team_sources": team_sources})
