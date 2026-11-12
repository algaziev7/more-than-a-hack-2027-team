"""Video-review projection checks using synthetic homographies and tracks."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts import review_kickoff_geometry as cli
from tests.test_kickoff import kickoff_match


class GeometryReviewTests(unittest.TestCase):
    def test_projection_converts_metres_back_to_normalized_coordinates(self):
        matrix = np.array([[1000., 0, 10], [0, 500, 20], [0, 0, 1]])
        pitch = (100., 50.)
        points = np.array([[0., 0.], [50., 25.], [100., 50.]])
        np.testing.assert_allclose(cli.project_metres(matrix, points, pitch),
                                   [[10, 20], [510, 270], [1010, 520]])

    def test_invalid_homography_and_missing_ball_remain_missing(self):
        match = kickoff_match()
        n = len(match.frame)
        matrices = np.tile(np.eye(3), (n, 1, 1))
        valid = np.ones(n, dtype=bool)
        valid[25] = False
        matrices[26] = 0  # Claimed valid but singular.
        match.ball_xy_m[27] = np.nan
        match.ball_observed[27] = False
        match.ball_speed_mps[27] = np.nan
        report = cli.make_overlay(match, matrices, np.zeros(n), valid, 25, 1, 1)
        self.assertFalse(report["frames"]["25"]["homography_valid"])
        self.assertFalse(report["frames"]["26"]["homography_valid"])
        self.assertIsNone(report["frames"]["27"]["ball"])
        self.assertEqual(report["frames"]["25"]["players"], [])
        np.testing.assert_allclose(report["frames"]["24"]["centre"], [.5, .5])

    def test_one_command_writes_viewer_without_reading_video(self):
        match = kickoff_match()
        n = len(match.frame)
        matrices = np.tile(np.eye(3), (n, 1, 1))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            homography = root/"synthetic.csv"
            homography.write_text("frame,valid\n"+"\n".join(f"{i},1" for i in range(n))+"\n")
            console = io.StringIO()
            with patch.object(cli, "ROOT", root), \
                    patch.object(cli, "load_config", return_value={}), \
                    patch.object(cli, "bundle_root", return_value=root), \
                    patch.object(cli, "asset_paths", return_value={"homography": homography}), \
                    patch.object(cli, "load_match", return_value=match), \
                    patch.object(cli, "load_homography", return_value=(matrices, np.zeros(n), np.ones(n, bool))), \
                    contextlib.redirect_stdout(console):
                self.assertEqual(cli.main(["--check-frame", "25", "--window-s", "1"]), 0)
            html = (root/"runs"/"kickoff-geometry"/"private-overlay.html").read_text()
            self.assertIn("connect-src 'none'", html)
            self.assertIn("URL.createObjectURL", html)
            self.assertNotIn("https://", html)
            self.assertNotIn(str(root), html)
            self.assertNotIn('"ball":', console.getvalue())

    def test_mismatched_frame_order_is_rejected(self):
        match = kickoff_match()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"synthetic.csv"
            path.write_text("frame,valid\n1,1\n0,1\n")
            with patch.object(cli, "load_config", return_value={}), \
                    patch.object(cli, "bundle_root", return_value=Path(directory)), \
                    patch.object(cli, "asset_paths", return_value={"homography": path}), \
                    patch.object(cli, "load_match", return_value=match), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.main(["--check-frame", "25"])


if __name__ == "__main__":
    unittest.main()
