"""Invented E2 inputs and repeatable boundary measurements, never match data.

Run ``python -m tests.e2_scenarios`` for a Markdown timing table. H/A are
decisive tracking hints, D is reliable stop support, . is no evidence, and R
is reliable live/restart support without a known team. These inputs bypass
E4 feature extraction; they do not constitute a complete prediction pipeline.
"""

from dataclasses import dataclass

import numpy as np

from possession.contracts import FeatureData, MatchData, PriorData
from possession.state_machine import decode


def evidence_sequence(symbols, *, fps=25., half=None):
    """Use the real shared contracts; geometry is deliberately unobserved."""
    if set(symbols) - set("HAD.R"):
        raise ValueError("unknown synthetic evidence symbol")
    n = len(symbols)
    frame = np.arange(n, dtype=np.int64)
    match = MatchData(
        frame=frame, half=np.ones(n, dtype=np.int8) if half is None
        else np.asarray(half, dtype=np.int8), fps=fps, pitch_m=(105., 68.),
        ball_xy_m=np.full((n, 2), np.nan), ball_observed=np.zeros(n, dtype=bool),
        players_xy_m=np.full((n, 2, 2), np.nan),
        player_observed=np.zeros((n, 2), dtype=bool), slot_team=np.array(["H", "A"]),
        metadata={"source": "invented E2 evidence"},
    )
    team = np.full((n, 2), .5)
    reliability = np.zeros(n)
    dead, dead_rel, restart = np.full(n, .5), np.zeros(n), np.zeros(n)
    for i, symbol in enumerate(symbols):
        if symbol in "HA":
            team[i] = (.95, .05) if symbol == "H" else (.05, .95)
            reliability[i] = .9
        elif symbol == "D":
            dead[i], dead_rel[i] = .9, .5
        elif symbol == "R":
            dead[i], dead_rel[i], restart[i] = .1, .5, .75
    features = FeatureData(frame.copy(), {}, {}, team, reliability)
    priors = PriorData(dead, dead_rel, restart, np.full((n, 2), .5), np.zeros(n))
    return match, features, priors


def label_transitions(labels, *, start=1):
    """Read boundaries from output labels, independently of decoder diagnostics."""
    return [(i, str(labels[i - 1]), str(labels[i]))
            for i in range(max(1, start), len(labels)) if labels[i] != labels[i - 1]]


@dataclass(frozen=True)
class TimingCase:
    name: str
    symbols: str
    expected: tuple
    # First 30 frames establish the initial state; measure subsequent events.
    start: int = 30


TIMING_CASES = (
    TimingCase("Turnover", "H" * 30 + "A" * 30, ((30, "H", "A"),)),
    TimingCase("Stop", "H" * 30 + "D" * 30, ((30, "H", "D"),)),
    # Decision 6 (2026-11-09): team evidence alone cannot exit a confirmed stop, so these two
    # cases now include a single "R" (restart/live-motion proof) at the same position the team
    # symbol used to start -- without it, "D"*30+"A"*30 would stay D forever, which is exactly
    # the bug Decision 6 fixes. The expected frame stays at the true moment of restart (where R
    # now sits); the measured delay below grows by 1 frame, the cost of requiring that proof.
    TimingCase("Restart", "D" * 30 + "R" + "A" * 29, ((30, "D", "A"),)),
    TimingCase("Same-team restart", "H" * 30 + "D" * 10 + "R" + "H" * 29,
               ((30, "H", "D"), (40, "D", "H"))),
    TimingCase("Turnover with 100-frame gap", "H" * 30 + "A" * 7 + "." * 100 + "A" * 8,
               ((30, "H", "A"),)),
    TimingCase("14-frame A possession", "H" * 30 + "A" * 14 + "H" * 30,
               ((30, "H", "A"), (44, "A", "H"))),
    TimingCase("15-frame A possession", "H" * 30 + "A" * 15 + "H" * 30,
               ((30, "H", "A"), (45, "A", "H"))),
    TimingCase("16-frame A possession", "H" * 30 + "A" * 16 + "H" * 30,
               ((30, "H", "A"), (46, "A", "H"))),
)


def measure_timing(case):
    """Match the unique (from,to) event types in each small invented scenario.

    No time tolerance is used: delays beyond scorer tolerances must remain
    visible. This is a boundary diagnostic, not the official transition score.
    Causal decoding places final boundaries at confirmation; the two delays are
    equal. Warm-up is excluded explicitly, rather than counted as a real event.
    """
    prediction = decode(*evidence_sequence(case.symbols))
    remaining = label_transitions(prediction.labels, start=case.start)
    errors, missed = [], 0
    for frame, before, after in case.expected:
        match = next((event for event in remaining if event[1:] == (before, after)), None)
        if match is None:
            missed += 1
        else:
            errors.append(match[0] - frame)
            remaining.remove(match)
    return errors, missed, len(remaining)


def timing_table():
    rows = ["| Synthetic case (25 fps) | Delay / final boundary error (frames) | Missed | Spurious |",
            "|---|---|---|---|"]
    for case in TIMING_CASES:
        errors, missed, spurious = measure_timing(case)
        delay = ", ".join(f"{error:+d}" for error in errors) or "—"
        rows.append(f"| {case.name} | {delay} | {missed} | {spurious} |")
    return "\n".join(rows)


if __name__ == "__main__":
    print(timing_table())
