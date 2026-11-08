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


def grouped_reference(symbols, half, team_required, dead_required):
    """Small offline oracle: remove neutral observations and group decisive runs.

    A run with enough observations starts a new state at its nth observation.
    Map that boundary back onto the original frame axis. This intentionally
    uses whole runs and suffix assignment, not production's pending counter.
    It only covers unambiguous symbols, not general evidence fusion.
    """
    labels = ["X"] * len(symbols)
    for half_id, indices in groupby(range(len(symbols)), key=lambda i: half[i]):
        indices = list(indices)
        if half_id == 0:
            continue
        first, last = indices[0], indices[-1] + 1
        labels[first:last] = ["D"] * (last - first)
        decisive = [i for i in indices if symbols[i] in "HAD"]
        for symbol, observations in groupby(decisive, key=lambda i: symbols[i]):
            observations = list(observations)
            required = dead_required if symbol == "D" else team_required
            if len(observations) >= required:
                boundary = observations[required - 1]
                labels[boundary:last] = [symbol] * (last - boundary)
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

    def test_pending_evidence_survives_long_gap_current_policy(self):
        # Characterization, not endorsement: a pending candidate has no expiry.
        result = decode(*evidence_sequence("H" * 30 + "A" * 14 + "." * 1000 + "A"))
        self.assertEqual(label_transitions(result.labels, start=30), [(1044, "H", "A")])

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
        expected = (([14], 0, 0), ([1], 0, 0), ([14], 0, 0),
                    ([1, 14], 0, 0), ([114], 0, 0), ([], 2, 0),
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
        config = {"state_machine": {"team_dwell_s": .12, "dead_dwell_s": .08}}
        for length in range(7):
            for symbols in product("HAD.", repeat=length):
                result = decode(*evidence_sequence(symbols), config)
                expected = grouped_reference(symbols, [1] * length, 3, 2)
                self.assertEqual(result.labels.tolist(), expected, "".join(symbols))

    def test_seeded_half_sequences_against_reference(self):
        rng = np.random.default_rng(20261108)
        config = {"state_machine": {"team_dwell_s": .12, "dead_dwell_s": .08}}
        for sample in range(200):
            symbols = rng.choice(list("HAD.R"), 80).tolist()
            half = [1] * 35 + [0] * 5 + [2] * 40
            result = decode(*evidence_sequence(symbols, half=half), config)
            self.assertEqual(result.labels.tolist(), grouped_reference(symbols, half, 3, 2), sample)

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
        config = {"state_machine": {"team_dwell_s": .2}, "tagging": {"enabled": False}}
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
        self.assertEqual(events, [(14, "D", "H"), (46, "H", "D"), (74, "D", "H")])
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
