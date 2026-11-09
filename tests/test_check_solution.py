from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from games import GAME, GAMES


CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_solution.py"


class CheckSolutionTests(unittest.TestCase):
    def test_propagates_official_validation_and_uses_full_length_by_default(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic submission.csv"
            rows = GAMES[GAME]["n_video_frames"]
            path.write_text("frame,label\n" + "".join(f"{i},X\n" for i in range(rows)),
                            encoding="utf-8")
            cmd = [sys.executable, str(CHECKER), str(path)]
            valid = subprocess.run(cmd, cwd=folder, capture_output=True, text=True)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertIn("OK", valid.stdout)

            path.write_text("frame,label\n0,X\n", encoding="utf-8")
            short = subprocess.run(cmd, cwd=folder, capture_output=True, text=True)
            self.assertEqual(short.returncode, 1, short.stderr)
            self.assertIn("FAIL", short.stdout)
