import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from games import GAME, GAMES
from possession.contracts import Prediction
from possession.export import write_submission
from possession.run_manifest import capture_run, write_run_manifest


class ManifestTests(unittest.TestCase):
    def prediction(self, n=None):
        n = GAMES[GAME]["n_video_frames"] if n is None else n
        run = capture_run({"seed": 17})
        run.update(runtime_s=.25, input_sha256={"synthetic": "0" * 64},
                   frame_count=n, checks={"shared_contracts": "pass"})
        return Prediction(np.resize(np.array(list("HADX")), n), {"run_manifest": run})

    def test_config_identity_is_canonical_and_source_identity_is_present(self):
        first = capture_run({"seed": 17, "schema_version": 1})
        second = capture_run({"schema_version": 1, "seed": 17})
        self.assertEqual(first["config_sha256"], second["config_sha256"])
        self.assertNotEqual(first["config_sha256"], capture_run({})["config_sha256"])
        self.assertIn("possession/pipeline.py", first["source_sha256"])
        self.assertIn("numpy", first["dependencies"])

    def test_exact_full_length_export_is_validated_and_recorded(self):
        prediction = self.prediction()
        original = copy.deepcopy(prediction.diagnostics)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = write_submission(prediction, root / "team.csv")
            path = write_run_manifest(prediction, output, root / "manifest.json")
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(record["checks"]["official_validator"], "pass")
            self.assertEqual(record["checks"]["exact_prediction_bytes"], "pass")
            self.assertEqual(record["seed"], 17)
            self.assertNotIn(str(root), path.read_text(encoding="utf-8"))
        self.assertEqual(prediction.diagnostics, original)

    def test_changed_output_or_wrong_length_cannot_claim_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prediction = self.prediction()
            output = write_submission(prediction, root / "team.csv")
            output.write_bytes(output.read_bytes().replace(b"0,H", b"0,A", 1))
            target = root / "manifest.json"
            target.write_text("previous", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                write_run_manifest(prediction, output, target)
            small = self.prediction(4)
            write_submission(small, output, n_expected=4)
            with self.assertRaisesRegex(ValueError, "official format"):
                write_run_manifest(small, output, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "previous")

    def test_manifest_cannot_overwrite_csv_and_failed_replace_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prediction = self.prediction()
            output = write_submission(prediction, root / "team.csv")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                write_run_manifest(prediction, output, output)
            with patch("possession.run_manifest.os.replace", side_effect=OSError("invented")):
                with self.assertRaises(OSError):
                    write_run_manifest(prediction, output, root / "manifest.json")
            self.assertEqual(list(root.iterdir()), [output])

    def test_missing_git_metadata_is_explicit(self):
        with patch("possession.run_manifest._git", return_value=None):
            run = capture_run({})
        self.assertIsNone(run["code_commit"])
        self.assertIsNone(run["tracked_worktree_dirty"])
        self.assertTrue(run["source_sha256"])


if __name__ == "__main__":
    unittest.main()
