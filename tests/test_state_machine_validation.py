"""Isken's independent policy, integration and regression checks for E2.

All inputs are invented. Expected boundaries are hand specified or derived by
an offline run-group oracle, never by production fusion/transition helpers.
"""

from copy import deepcopy
from itertools import groupby, product
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from evaluation import possession_metrics as pm
from possession.dead_ball import build_priors
from possession.export import write_submission
from possession.state_machine import decode
from tests.e2_scenarios import TIMING_CASES, evidence_sequence, label_transitions, measure_timing


def grouped_reference(symbols, half, team_required, dead_required, latched_required=None):
    """Independent re-derivation of the decode() policy from its prose description.

    Through 2026-11-08 this was a purely declarative "group runs, check each run's own length,
    suffix-assign from its boundary" oracle, deliberately avoiding production's pending-occurrence
    counter for structural independence. Decision 6 (2026-11-09) broke that: whether an H/A
    observation counts at all now depends on the *current state* and a *dead_confirmed* latch at
    that exact moment, both of which only make sense evaluated in temporal sequence -- a single D
    observation can latch the flag without itself transitioning the state; an R between two
    otherwise-qualifying H observations doesn't break their run (Decision 3: a non-decisive frame
    pauses a pending count, it doesn't reset it) but does clear the latch mid-run. No declarative
    whole-run check can express that without silently becoming wrong in some case (as happened
    twice while developing this update). So this is now a sequential walk, each piece re-derived
    independently from the written policy (not by importing or calling state_machine.decode) --
    less structurally different from production than the original design, but still a second,
    independently-authored implementation of the same prose spec, which is what actually matters
    for catching a transcription or off-by-one error in either one.

    `latched_required` (Decision 6's safety valve, added after a later review demonstrated the
    latch could otherwise pin D indefinitely): while gated, an H/A candidate still accumulates,
    but against this much longer requirement instead of team_required. The moment R lifts the
    gate, any *team*-candidate progress accumulated under that longer requirement is discarded
    (re-derived independently from the same reasoning as production's: letting it carry over
    toward the now-much-shorter team_required would let a long "banked" run of mere proximity
    cash in the instant a single frame of real proof arrives) -- a pending D-candidate, unrelated
    to the gate, is untouched. Defaults to `team_required` (no safety valve distinguishable from
    ordinary gating) when omitted, for callers that don't exercise it.

    R also discards a pending D-candidate (2026-11-10, Almaz's review): confirmed live play
    between two isolated stop observations means they are not one stop. The evidence-age window
    (evidence_window_s, ~150 frames by default) is not modelled: every sequence here is shorter.
    """
    if latched_required is None:
        latched_required = team_required
    labels = ["X"] * len(symbols)
    for half_id, indices in groupby(range(len(symbols)), key=lambda i: half[i]):
        indices = list(indices)
        if half_id == 0:
            continue
        state, dead_confirmed = "D", False
        pending_symbol, pending_count = None, 0
        for i in indices:
            symbol = symbols[i]
            if symbol == "D":
                dead_confirmed = True
            elif symbol == "R" and dead_confirmed:
                dead_confirmed = False
                # Only discard a candidate that was actually subject to the gate -- a single D
                # observation can latch dead_confirmed without state ever becoming "D" (it never
                # reached dead_required), so without the state == "D" guard, a later R would
                # wipe an ordinary, never-gated run's progress for no reason.
                if pending_symbol in ("H", "A") and state == "D":
                    pending_symbol, pending_count = None, 0
            if symbol == "R" and pending_symbol == "D":
                pending_symbol, pending_count = None, 0

            candidate = symbol if symbol in "HAD" else None
            if candidate is None:
                labels[i] = state
                continue
            if candidate == state:
                pending_symbol, pending_count = None, 0
                labels[i] = state
                continue
            pending_count = pending_count + 1 if candidate == pending_symbol else 1
            pending_symbol = candidate
            if candidate == "D":
                required = dead_required
            elif state == "D" and dead_confirmed:
                required = latched_required
            else:
                required = team_required
            if pending_count >= required:
                if state == "D" and candidate != "D":
                    # Leaving D: don't carry a stale latch into the live period that follows.
                    dead_confirmed = False
                state = candidate
                pending_symbol, pending_count = None, 0
            labels[i] = state
    return labels


class StateMachineValidationTests(unittest.TestCase):
    def test_default_dwell_uses_match_fps(self):
        for fps, first_home in ((10., 5), (25., 14), (50., 29)):
            with self.subTest(fps=fps):
                prediction = decode(*evidence_sequence("H" * 60, fps=fps))
                self.assertEqual(np.flatnonzero(prediction.labels == "H")[0], first_home)

    def test_fractional_dwell_never_rounds_below_required_observations(self):
        # 0.1 s at 25 fps requires 3 observations, not Python round(2.5) == 2.
        config = {"state_machine": {"team_dwell_s": .1, "dead_dwell_s": .1}}
        result = decode(*evidence_sequence("H" * 5 + "D" * 5), config)
        self.assertEqual(result.labels.tolist(), list("DDHHHHHDDD"))

    def test_explicit_fps_must_agree_with_match(self):
        inputs = evidence_sequence("H" * 60, fps=50.)
        with self.assertRaisesRegex(ValueError, "fps.*match"):
            decode(*inputs, {"state_machine": {"fps": 25.}})
        same = decode(*inputs, {"state_machine": {"fps": 50.}})
        np.testing.assert_array_equal(same.labels, decode(*inputs).labels)

    def test_mismatched_valid_contract_lengths_fail_before_broadcast_or_truncation(self):
        match, features, priors = evidence_sequence("H" * 10)
        for n in (1, 9, 11):
            _, other_features, other_priors = evidence_sequence("A" * n)
            for field, args in (("features", (match, other_features, priors)),
                                ("priors", (match, features, other_priors))):
                with self.subTest(field=field, n=n):
                    with self.assertRaisesRegex(ValueError, field):
                        decode(*args)

    def test_misaligned_feature_frames_fail(self):
        match, features, priors = evidence_sequence("H" * 20)
        features.frame = features.frame[::-1].copy()
        with self.assertRaisesRegex(ValueError, "frame"):
            decode(match, features, priors)

    def test_thresholds_and_weights_are_bounded(self):
        inputs = evidence_sequence("H")
        for name in ("dead_threshold", "dead_reliability_min", "restart_weight",
                     "team_margin_threshold", "team_reliability_min"):
            for value in (-.01, 1.01):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, name):
                        decode(*inputs, {"state_machine": {name: value}})

    def test_evidence_window_must_cover_every_dwell(self):
        with self.assertRaisesRegex(ValueError, "evidence_window_s"):
            decode(*evidence_sequence("H"), {"state_machine": {"evidence_window_s": .5}})

    def test_live_and_dead_thresholds_cannot_overlap(self):
        # Beks's review: overlapping thresholds let one stop clue set and clear the latch.
        for settings in ({"live_confirmed_threshold": .9},
                         {"live_confirmed_threshold": .6, "dead_threshold": .6}):
            with self.subTest(**settings):
                with self.assertRaisesRegex(ValueError, "live_confirmed_threshold"):
                    decode(*evidence_sequence("H"), {"state_machine": settings})

    def test_conflicting_restart_cannot_clear_a_confirmed_stop(self):
        for team in ("H", "A"):
            with self.subTest(team=team):
                match, features, priors = evidence_sequence(team * 30 + "D" * 10 + team * 20)
                # Both signals meet their default thresholds: adjusted dead=.65,
                # restart=.6. A dead decision must keep the stop latch set.
                priors.dead_evidence[30:40] = .95
                priors.restart_evidence[30:40] = .6
                result = decode(match, features, priors)
                self.assertTrue(np.all(result.labels[31:] == "D"))
                # A later unopposed restart must still release it normally.
                priors.restart_evidence[40] = .75
                result = decode(match, features, priors)
                self.assertEqual(label_transitions(result.labels, start=30),
                                 [(31, team, "D"), (54, "D", team)])

    def test_stop_fallback_requires_longer_support_than_ordinary_dwell(self):
        for settings in ({"latched_team_dwell_s": .04},
                         {"latched_team_dwell_s": .6}, {"team_dwell_s": 4.}):
            with self.subTest(**settings):
                with self.assertRaisesRegex(ValueError, "latched_team_dwell_s"):
                    decode(*evidence_sequence("H"), {"state_machine": settings})
        # Check rounded counts at the actual match rate, not the 25-fps fallback.
        config = {"state_machine": {"team_dwell_s": .1, "latched_team_dwell_s": .11}}
        with self.assertRaisesRegex(ValueError, "latched_team_dwell_s"):
            decode(*evidence_sequence("H"), config)  # both ceil to 3 at 25 fps
        result = decode(*evidence_sequence("H" * 20, fps=100.), config)
        self.assertEqual(result.labels.tolist(), list("D" * 9 + "H" * 11))

    def test_zero_team_floors_do_not_turn_absent_or_tied_evidence_into_home(self):
        config = {"state_machine": {"team_reliability_min": 0., "team_margin_threshold": 0.}}
        for weight in (0., .9):
            with self.subTest(weight=weight):
                match, features, priors = evidence_sequence("." * 30)
                features.team_reliability[:] = weight
                result = decode(match, features, priors, config)
                self.assertTrue(np.all(result.labels == "D"))
        # Zero floors must still allow a genuine, positively weighted team clue.
        result = decode(*evidence_sequence("A" * 30), config)
        self.assertEqual(result.labels.tolist(), list("D" * 14 + "A" * 16))

    def test_zero_dead_floor_does_not_promote_zero_weight_stop_evidence(self):
        config = {"state_machine": {"dead_reliability_min": 0., "dead_threshold": .5}}
        result = decode(*evidence_sequence("H" * 30), config)
        self.assertEqual(result.labels.tolist(), list("D" * 14 + "H" * 16))

    def test_team_margin_boundary_is_inclusive_and_symmetric(self):
        for source in ("tracking", "tagging", "both"):
            for offset in (-1e-9, 0., 1e-9):
                for team in ("H", "A"):
                    with self.subTest(source=source, offset=offset, team=team):
                        match, features, priors = evidence_sequence("." * 40)
                        pair = [.575 + offset, .425 - offset]
                        if team == "A":
                            pair.reverse()
                        if source in ("tracking", "both"):
                            features.team_evidence[:] = pair
                            features.team_reliability[:] = .9
                        if source in ("tagging", "both"):
                            priors.tag_team_evidence[:] = pair
                            priors.tag_team_reliability[:] = .5
                        result = decode(match, features, priors)
                        expected = "D" * 40 if offset < 0 else "D" * 14 + team * 26
                        self.assertEqual(result.labels.tolist(), list(expected))

    def test_live_play_between_stop_clues_does_not_enter_dead(self):
        # Beks's review: isolated stops split by a restart and live play must not combine.
        result = decode(*evidence_sequence(
            "H" * 30 + "D" + "." * 4 + "R" * 6 + "." * 14 + "D" + "." * 20))
        self.assertEqual(label_transitions(result.labels, start=30), [])

    def test_dead_ball_weight_below_decoder_floor_fails(self):
        # Review note: evidence_weight becomes dead_reliability, so 0.25 < 0.3 silently disables D.
        inputs = evidence_sequence("H")
        with self.assertRaisesRegex(ValueError, "evidence_weight"):
            decode(*inputs, {"dead_ball": {"evidence_weight": .25}})
        for ok in ({"evidence_weight": 0.}, {"enabled": False, "evidence_weight": .25},
                   {"evidence_weight": .3}):
            with self.subTest(**ok):
                decode(*inputs, {"dead_ball": ok})

    def test_empty_single_and_excluded_frames(self):
        for symbols, half, expected in (("", [], ""), ("H", [1], "D"),
                                        ("HAD", [0, 0, 0], "XXX"),
                                        ("...", [1, 1, 1], "DDD")):
            with self.subTest(symbols=symbols):
                result = decode(*evidence_sequence(symbols, half=half))
                self.assertEqual(result.labels.tolist(), list(expected))
                self.assertEqual(result.diagnostics["transitions"], [])

    def test_long_missing_gap_does_not_create_stop_or_turnover(self):
        result = decode(*evidence_sequence("H" * 30 + "." * 1000))
        self.assertTrue(np.all(result.labels[14:] == "H"))

    def test_pending_evidence_expires_after_evidence_window(self):
        # Almaz's review (2026-11-10): 40s-old support must not combine with a fresh touch.
        result = decode(*evidence_sequence("H" * 30 + "A" * 14 + "." * 1000 + "A"))
        self.assertEqual(label_transitions(result.labels, start=30), [])
        # Within the default 150-frame window the gap is still tolerated (Decision 3).
        result = decode(*evidence_sequence("H" * 30 + "A" * 14 + "." * 130 + "A"))
        self.assertEqual(label_transitions(result.labels, start=30), [(174, "H", "A")])
        # Just outside it, the oldest support has aged out.
        result = decode(*evidence_sequence("H" * 30 + "A" * 14 + "." * 137 + "A"))
        self.assertEqual(label_transitions(result.labels, start=30), [])

    def test_confirmed_live_play_cancels_pending_stop(self):
        # Almaz's review (2026-11-10): two isolated stop frames split by live play are not a stop.
        result = decode(*evidence_sequence("H" * 30 + "D" + "R" * 25 + "D" + "." * 50))
        self.assertEqual(label_transitions(result.labels, start=30), [])
        # Without live play between them they still combine (Decision 3 pause, not reset).
        result = decode(*evidence_sequence("H" * 30 + "D" + "." * 25 + "D" + "." * 50))
        self.assertEqual(label_transitions(result.labels, start=30), [(56, "H", "D")])

    def test_incumbent_support_cancels_pending_turnover(self):
        result = decode(*evidence_sequence("H" * 30 + "A" * 14 + "H" + "A" * 15))
        self.assertEqual(label_transitions(result.labels, start=30), [(59, "H", "A")])

    def test_competing_stop_candidate_cancels_pending_turnover(self):
        # One stop observation cannot establish D, but invalidates the A run.
        result = decode(*evidence_sequence("H" * 30 + "A" * 14 + "D" + "A" * 15))
        self.assertEqual(label_transitions(result.labels, start=30), [(59, "H", "A")])

    def test_unknown_team_restart_does_not_guess_team_current_policy(self):
        result = decode(*evidence_sequence("H" * 30 + "D" * 10 + "R" * 50 + "A" * 15))
        self.assertTrue(np.all(result.labels[40:104] == "D"))
        self.assertEqual(label_transitions(result.labels, start=30),
                         [(31, "H", "D"), (104, "D", "A")])

    def test_half_reset_discards_pending_and_confirmed_state(self):
        for gap in (0, 5):
            for first in ("H" * 30 + "A" * 14, "A" * 30 + "H" * 14):
                with self.subTest(gap=gap, first=first[0]):
                    symbols = first + "A" * gap + "A" * 20
                    half = [1] * len(first) + [0] * gap + [2] * 20
                    result = decode(*evidence_sequence(symbols, half=half))
                    self.assertEqual(result.labels[-20:].tolist(), list("D" * 14 + "A" * 6))
                    self.assertTrue(np.all(result.labels[len(first):len(first) + gap] == "X"))

    def test_final_frame_confirms_only_when_dwell_completed(self):
        for count in (14, 15):
            with self.subTest(count=count):
                result = decode(*evidence_sequence("H" * 30 + "A" * count))
                events = [] if count == 14 else [(44, "H", "A")]
                self.assertEqual(label_transitions(result.labels, start=30), events)

    def test_measured_boundaries_and_missed_short_possession(self):
        # Decision 6 (2026-11-09): Restart and Same-team restart now carry +1 frame extra delay --
        # the cost of requiring the inserted "R" (restart proof) before team evidence counts.
        expected = (([14], 0, 0), ([1], 0, 0), ([15], 0, 0),
                    ([1, 15], 0, 0), ([114], 0, 0), ([], 2, 0),
                    ([14, 14], 0, 0), ([14, 14], 0, 0))
        for case, wanted in zip(TIMING_CASES, expected):
            with self.subTest(case=case.name):
                self.assertEqual(measure_timing(case), wanted)
                result = decode(*evidence_sequence(case.symbols))
                recorded = [(t["frame"], t["from_state"], t["to_state"])
                            for t in result.diagnostics["transitions"]]
                self.assertEqual(recorded, label_transitions(result.labels))

    def test_exhaustive_short_sequences_against_offline_grouped_reference(self):
        # 5,461 sequences, including empty; neutral gaps keep their frame offsets.
        # latched_required=75 matches state_machine's actual default latched_team_dwell_frames
        # (not overridden by this config) -- unreachable within length <= 6 either way, kept
        # explicit so this doesn't silently rely on the oracle's own default being coincidentally
        # equivalent to "no safety valve, same as ordinary gating" (team_required, 3).
        config = {"state_machine": {"team_dwell_s": .12, "dead_dwell_s": .08}}
        for length in range(7):
            for symbols in product("HAD.", repeat=length):
                result = decode(*evidence_sequence(symbols), config)
                expected = grouped_reference(symbols, [1] * length, 3, 2, latched_required=75)
                self.assertEqual(result.labels.tolist(), expected, "".join(symbols))

    def test_seeded_half_sequences_against_reference(self):
        rng = np.random.default_rng(20261108)
        config = {"state_machine": {"team_dwell_s": .12, "dead_dwell_s": .08}}
        for sample in range(200):
            symbols = rng.choice(list("HAD.R"), 80).tolist()
            half = [1] * 35 + [0] * 5 + [2] * 40
            result = decode(*evidence_sequence(symbols, half=half), config)
            expected = grouped_reference(symbols, half, 3, 2, latched_required=75)
            self.assertEqual(result.labels.tolist(), expected, sample)

    def test_team_swap_symmetry_with_conflicting_geometry_and_tags(self):
        rng = np.random.default_rng(42)
        for sample in range(50):
            match, features, priors = evidence_sequence("." * 120)
            home = rng.choice([.05, .25, .5, .75, .95], 120)
            features.team_evidence[:] = np.column_stack((home, 1 - home))
            features.team_reliability[:] = .8
            tag_home = rng.choice([.05, .5, .95], 120)
            priors.tag_team_evidence[:] = np.column_stack((tag_home, 1 - tag_home))
            priors.tag_team_reliability[:] = .5
            priors.dead_evidence[40:50], priors.dead_reliability[40:50] = .9, .5
            match.half[60:65], match.half[65:] = 0, 2
            config = {"state_machine": {"team_dwell_s": .08}}
            original = decode(match, features, priors, config)
            features.team_evidence = features.team_evidence[:, ::-1].copy()
            priors.tag_team_evidence = priors.tag_team_evidence[:, ::-1].copy()
            swapped = decode(match, features, priors, config)
            expected = [{"H": "A", "A": "H", "D": "D", "X": "X"}[x]
                        for x in original.labels]
            self.assertEqual(swapped.labels.tolist(), expected, sample)

    def test_repeated_calls_preserve_inputs_and_config(self):
        inputs = evidence_sequence("H" * 30 + "D" * 10 + "A" * 30)
        # "enabled" is a dead_ball.DeadBallConfig field, not TaggingConfig's -- decode() now
        # validates the tagging section strictly (Decision 6's restart-threshold guard), so this
        # uses a real TaggingConfig field instead of one that only ever worked by accident. Kept
        # below state_machine's default restart_evidence_threshold (0.6), which that same guard
        # requires.
        config = {"state_machine": {"team_dwell_s": .2}, "tagging": {"restart_strength": .4}}
        before = deepcopy((inputs, config))
        first = decode(*inputs, config)
        decode(*evidence_sequence("A" * 20))
        second = decode(*inputs, config)
        np.testing.assert_array_equal(first.labels, second.labels)
        self.assertEqual(first.diagnostics, second.diagnostics)
        for original, copy in zip(inputs, before[0]):
            for name, value in vars(original).items():
                if isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(value, getattr(copy, name))
                else:
                    self.assertEqual(value, getattr(copy, name))
        self.assertEqual(config, before[1])

    def test_e3_priors_decode_and_export_synthetic_vertical_slice(self):
        # An invented in-pitch moving ball, then outside/still, then a restart.
        match, features, _ = evidence_sequence("H" * 30 + "." * 30 + "H" * 40)
        xy = np.column_stack((np.arange(100) * .12 + 10., np.full(100, 20.)))
        xy[30:60] = (-1., 20.)
        match.ball_xy_m = xy
        match.ball_observed[:] = True
        match.ball_speed_mps = np.full(100, 3.)
        match.ball_speed_mps[30:60] = 0.
        priors = build_priors(match, features)
        prediction = decode(match, features, priors)
        events = label_transitions(prediction.labels)
        self.assertEqual([(a, b) for _, a, b in events], [("D", "H"), ("H", "D"), ("D", "H")])
        # E3 first rejects the jump, then needs 15 still observations; E2 adds one frame.
        # Decision 6 (2026-11-09): the final restart now also waits for E3's own confirmed-live
        # signal before team evidence counts at all (74 -> 79) -- team proximity alone is no
        # longer enough to leave a confirmed stop, which is the whole point of that decision.
        self.assertEqual(events, [(14, "D", "H"), (46, "H", "D"), (79, "D", "H")])
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "first.csv", Path(temporary) / "second.csv"
            write_submission(prediction, first, n_expected=100)
            write_submission(decode(match, features, priors), second, n_expected=100)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            check = subprocess.run(
                [sys.executable, "evaluation/validate_submission.py", str(first), "--rows", "100"],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)


class E2MetricContractTests(unittest.TestCase):
    def test_official_metric_on_invented_perfect_sequence(self):
        labels = pm.label_codes(list("HHDDDAAAHH"))
        result = pm.evaluate(labels, labels, bootstrap_n=0)
        self.assertEqual(result["macro_f1"], 1.)
        self.assertEqual(result["spell_f1_mean"], 1.)
        self.assertEqual(result["n_gt_spells"], 3)

    def test_abstention_filling_does_not_cross_ungraded_gap(self):
        truth = pm.label_codes(list("HHXXAA"))
        prediction = pm.label_codes(list("HXXXAX"))
        result = pm.evaluate(truth, prediction, bootstrap_n=0)
        self.assertEqual(result["n_pred_spells"], 2)
        self.assertEqual(result["spell_f1_mean"], 1.)
        self.assertEqual(result["accuracy"], .5)

    def test_dead_ball_separates_same_team_spells(self):
        labels = pm.label_codes(list("HHDHH"))
        result = pm.evaluate(labels, labels, bootstrap_n=0)
        self.assertEqual(result["n_pred_spells"], 2)
        self.assertEqual(result["spell_f1_mean"], 1.)


if __name__ == "__main__":
    unittest.main()
