"""Consolidated debugging on invented matches only."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from possession.dead_ball import build_priors
from possession.features import build_features
from possession.state_machine import decode
from scripts import debug_kickoff as cli
from tests.test_kickoff import kickoff_match
from tests.test_kickoff_source import METADATA


class DebugKickoffTests(unittest.TestCase):
    def test_one_command_writes_complete_reports_using_synthetic_sources(self):
        match = kickoff_match()
        console = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            meta = root/"synthetic.xml"
            meta.write_text(METADATA)
            with patch.object(cli, "ROOT", root), \
                    patch.object(cli, "load_config", return_value={}), \
                    patch.object(cli, "load_match", return_value=match), \
                    patch.object(cli, "asset_paths", return_value={"atd_meta": meta}), \
                    contextlib.redirect_stdout(console):
                self.assertEqual(cli.main(["--half", "1", "--check-frame", "25"]), 0)
            folder = root/"runs"/"kickoff-debug"
            report = json.loads((folder/"private-report.json").read_text())
            self.assertEqual(report["decoder_status"], "HALF_START_GATE_NOT_IN_CHECKOUT")
            self.assertEqual(len(report["kickoff_confirmations"]), 1)
            self.assertTrue(any(row["frame"] == 25 for row in report["snapshots"]))
            summary = (folder/"shareable-summary.txt").read_text()
            for forbidden in ("check_frame", "snapshots", "players", "counts", "25", str(root)):
                self.assertNotIn(forbidden, summary)
            self.assertIn("NORMALIZED_XY_DECLARED", summary)
            self.assertNotIn("NORMALIZED_XY_DECLARED", console.getvalue())
            self.assertNotIn("https://", (folder/"private-report.html").read_text())

    def test_check_frame_does_not_change_inference_and_missing_ball_is_not_imputed(self):
        match = kickoff_match()
        match.ball_xy_m[26] = np.nan
        match.ball_observed[26] = False
        match.ball_speed_mps[26] = np.nan
        features = build_features(match)
        priors = build_priors(match, features)
        prediction = decode(match, features, priors)
        labels = prediction.labels.copy()
        for check in (25, 26):
            report = cli.investigate(match, features, priors, prediction, {}, check, 1, 1.)
            self.assertTrue(any(row["frame"] == check for row in report["snapshots"]))
            missing = next(row for row in report["snapshots"] if row["frame"] == 26)
            self.assertIsNone(missing["ball"])
        np.testing.assert_array_equal(prediction.labels, labels)
        with self.assertRaises(ValueError):
            cli.investigate(match, features, priors, prediction, {}, 25, 2, 1.)

    def test_html_escapes_config_script_delimiters_and_summary_omits_config(self):
        match = kickoff_match()
        features = build_features(match)
        priors = build_priors(match, features)
        prediction = decode(match, features, priors)
        report = cli.investigate(match, features, priors, prediction, {}, 25, 1, 1.)
        report["config"]["test"] = "</script><script>PRIVATE_TEST</script>"
        report["source"] = {"position_units": "NORMALIZED_XY_DECLARED"}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cli.write_reports(report, folder)
            html = (folder/"private-report.html").read_text()
            self.assertNotIn("</script><script>PRIVATE_TEST", html)
            self.assertIn("\\u003c/script>", html)
            self.assertNotIn("PRIVATE_TEST", (folder/"shareable-summary.txt").read_text())


if __name__ == "__main__":
    unittest.main()
