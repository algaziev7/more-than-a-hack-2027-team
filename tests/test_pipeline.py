"""E5 wiring checks use invented inputs and an explicitly test-only decoder."""

import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from possession.contracts import FeatureData, Prediction, PriorData
from possession.export import write_submission
from possession.pipeline import predict_match
from tests.fixtures import neutral_features, neutral_priors, synthetic_match
from tests.test_data import META, ROWS


def decoder_module(function):
    module = types.ModuleType("possession.state_machine")
    module.decode = function
    return module


class PipelineTests(unittest.TestCase):
    def test_real_loader_features_priors_and_export_with_no_tags(self):
        """Only E2 is replaced; on-disk ATD rows are the invented E1 fixture."""
        calls = []

        def decode(match, features, priors, config):
            calls.append((match, features, priors, config))
            self.assertIsInstance(features, FeatureData)
            self.assertIsInstance(priors, PriorData)
            np.testing.assert_array_equal(features.frame, match.frame)
            self.assertEqual(match.events, [])
            np.testing.assert_array_equal(priors.tag_team_reliability, 0)
            return Prediction(np.array(list("HDXA")), {"test_only": True})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tactical = root / "tactical"
            tactical.mkdir()
            (tactical / "BAR-ATH_tactical_atd.xml").write_text(META, encoding="utf-8")
            (tactical / "BAR-ATH_tactical_atd.txt").write_text(
                "\n".join(ROWS) + "\n", encoding="utf-8")
            spec = {"BAR-ATH": {"n_video_frames": 4, "fps": 25, "pitch": (105.3, 68.)}}
            with patch.dict(sys.modules, {"possession.state_machine": decoder_module(decode)}), \
                    patch("possession.data.GAMES", spec), \
                    patch("possession.data.half_video_blocks", return_value=[(1, 0, 1), (2, 3, 3)]):
                first = predict_match(root, {"data": {"load_tags": True}})
                second = predict_match(root, {"data": {"load_tags": False}})
            one = write_submission(first, root / "one.csv", n_expected=4)
            two = write_submission(second, root / "two.csv", n_expected=4)
            self.assertEqual(one.read_bytes(), two.read_bytes())
            run = first.diagnostics["run_manifest"]
            self.assertEqual(set(run["input_sha256"]), {"atd_meta", "atd_raw"})
            self.assertNotIn(str(root), str(run))
            self.assertEqual(run["checks"]["frame_alignment"], "pass")
            self.assertGreaterEqual(run["runtime_s"], 0)
        self.assertEqual(len(calls), 2)

    def test_stage_order_config_and_input_preservation(self):
        match = synthetic_match()
        original = copy.deepcopy(match)
        features, priors = neutral_features(match), neutral_priors(match)
        decoded = Prediction(np.array(list("XHHXXAAX")), {"reasons": ["invented"]})
        order = []
        configs = []
        config = {"seed": 42, "dead_ball": {"enabled": False}}
        before = copy.deepcopy(config)

        def stage(name, result):
            def call(*args, **kwargs):
                order.append(name)
                configs.append(kwargs["config"])
                if name == "priors":
                    self.assertIs(kwargs["features"], features)
                return result
            return call

        with patch.dict(sys.modules, {"possession.state_machine":
                                     decoder_module(stage("decode", decoded))}), \
                patch("possession.pipeline.load_match", side_effect=stage("load", match)), \
                patch("possession.pipeline.build_features", side_effect=stage("features", features)), \
                patch("possession.pipeline.build_priors", side_effect=stage("priors", priors)):
            result = predict_match("invented", config)
        self.assertEqual(order, ["load", "features", "priors", "decode"])
        self.assertTrue(all(item == before for item in configs))
        self.assertEqual(config, before)
        self.assertEqual(result.diagnostics["reasons"], ["invented"])
        self.assertNotIn("run_manifest", decoded.diagnostics)
        self.assertFalse(np.shares_memory(result.labels, decoded.labels))
        np.testing.assert_array_equal(match.ball_xy_m, original.ball_xy_m)
        self.assertEqual(match.events, original.events)

    def test_missing_decoder_fails_before_loading_data(self):
        with patch("possession.pipeline.load_match") as loader, \
                patch("possession.pipeline.importlib.import_module",
                      side_effect=ModuleNotFoundError(name="possession.state_machine")):
            with self.assertRaisesRegex(RuntimeError, "E2 decoder is unavailable"):
                predict_match()
            loader.assert_not_called()

    def test_internal_import_failure_is_not_hidden(self):
        with patch("possession.pipeline.importlib.import_module",
                   side_effect=ModuleNotFoundError(name="internal_dependency")):
            with self.assertRaises(ModuleNotFoundError):
                predict_match()

    def test_invalid_config_fails_before_decoder_import(self):
        with patch("possession.pipeline.importlib.import_module") as importer:
            with self.assertRaises(ValueError):
                predict_match(config={"seed": -1})
            importer.assert_not_called()

    def test_noncallable_decoder_is_actionable(self):
        with patch.dict(sys.modules, {"possession.state_machine": decoder_module(None)}):
            with self.assertRaisesRegex(RuntimeError, "must expose"):
                predict_match()

    def test_cross_stage_mismatches_and_invalid_predictions_are_rejected(self):
        match = synthetic_match()
        # A valid smaller timeline, incompatible with the full synthetic match.
        small_features = FeatureData(np.arange(1, dtype=np.int64), {}, {},
                                     np.full((1, 2), .5), np.zeros(1))
        small_priors = PriorData(np.full(1, .5), np.zeros(1), np.zeros(1),
                                 np.full((1, 2), .5), np.zeros(1))
        for features, priors, prediction, error, message in (
            (small_features, neutral_priors(match), None, ValueError, "features and match"),
            (neutral_features(match), small_priors, None, ValueError, "priors and match"),
            (neutral_features(match), neutral_priors(match), Prediction(np.array(["X"])),
             ValueError, "prediction and match"),
            (neutral_features(match), neutral_priors(match), Prediction(np.full(8, "H")),
             ValueError, "outside"),
            (None, neutral_priors(match), None, TypeError, "E4"),
            (neutral_features(match), None, None, TypeError, "E3"),
            (neutral_features(match), neutral_priors(match), None, TypeError, "E2"),
        ):
            with self.subTest(message=message), \
                    patch.dict(sys.modules, {"possession.state_machine":
                                             decoder_module(lambda *a, **k: prediction)}), \
                    patch("possession.pipeline.load_match", return_value=match), \
                    patch("possession.pipeline.build_features", return_value=features), \
                    patch("possession.pipeline.build_priors", return_value=priors):
                with self.assertRaisesRegex(error, message):
                    predict_match()


@unittest.skipUnless(importlib.util.find_spec("possession.state_machine"),
                     "E2 decoder has not been integrated")
class DecoderIntegrationTests(unittest.TestCase):
    def test_full_length_invented_match_passes_official_validation(self):
        from games import GAME, GAMES
        from possession.contracts import MatchData
        from possession.run_manifest import write_run_manifest

        n = GAMES[GAME]["n_video_frames"]
        players = np.tile(np.array([[[10., 20.], [60., 20.]]]), (n, 1, 1))
        ball = np.tile(np.array([[10.1, 20.]]), (n, 1))
        ball[n // 2:] = [60.1, 20.]
        half = np.ones(n, dtype=np.int8)
        half[n // 2:] = 2
        half[[0, -1]] = 0
        # Geometry and half locations are invented, not match observations.
        match = MatchData(np.arange(n, dtype=np.int64), half, 25., (105.3, 68.),
                          ball, np.ones(n, bool), players, np.ones((n, 2), bool),
                          np.array(["H", "A"]))
        with patch("possession.pipeline.load_match", return_value=match):
            prediction = predict_match()
        self.assertEqual(prediction.labels[n // 2 - 1], "H")
        # Decision 8 (E2): the second half earns A from its first frame, nothing carried over.
        self.assertEqual(prediction.labels[n // 2], "A")
        self.assertEqual(prediction.labels[-2], "A")
        with tempfile.TemporaryDirectory() as directory:
            output = write_submission(prediction, Path(directory) / "invented.csv")
            write_run_manifest(prediction, output, Path(directory) / "manifest.json")

    def test_real_pipeline_team_swap_half_reset_and_repeatable_export(self):
        from possession.contracts import MatchData
        n = 110
        players = np.tile(np.array([[[10., 20.], [60., 20.]]]), (n, 1, 1))
        ball = np.tile(np.array([[10.1, 20.]]), (n, 1))
        # 30 frames each side: past E2's 25-frame team dwell (Decision 8). E4 rejects the frame
        # where the ball jumps 50 m (30), so A's support starts at 31.
        ball[30:60] = [60.1, 20.]
        half = np.r_[np.ones(60), np.zeros(5), np.full(45, 2)].astype(np.int8)
        match = MatchData(np.arange(n, dtype=np.int64), half, 25., (105.3, 68.),
                          ball, np.ones(n, bool), players, np.ones((n, 2), bool),
                          np.array(["H", "A"]))
        with patch("possession.pipeline.load_match", return_value=match):
            first, second = predict_match(), predict_match()
        self.assertEqual(first.labels[30], "H")
        self.assertEqual(first.labels[31], "A")  # backdated to the first supported A frame
        self.assertEqual(first.labels[59], "A")
        self.assertEqual(first.labels[65], "H")  # second half earns H from its own first frame
        self.assertEqual(first.labels[-1], "H")
        swapped = copy.deepcopy(match)
        swapped.slot_team = np.array(["A", "H"])
        with patch("possession.pipeline.load_match", return_value=swapped):
            result = predict_match()
        mapping = {"H": "A", "A": "H", "D": "D", "X": "X"}
        np.testing.assert_array_equal(result.labels, [mapping[v] for v in first.labels])
        with tempfile.TemporaryDirectory() as directory:
            one = write_submission(first, Path(directory) / "one.csv", n_expected=n)
            two = write_submission(second, Path(directory) / "two.csv", n_expected=n)
            self.assertEqual(one.read_bytes(), two.read_bytes())


if __name__ == "__main__":
    unittest.main()
