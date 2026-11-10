import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("repository_policy", ROOT / ".github/check_repository.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class RepositoryPolicyTests(unittest.TestCase):
    def test_private_paths_are_ignored_and_rejected_without_opening_them(self):
        names = ["data/example.txt", "runs/final/team.csv", "artifacts/cache/a.npz",
                 ".local/manifest.json", ".env", "example.npy", "example.pkl",
                 "example_atd.txt", "example_atd.xml", "example_smart_tagging.xml"]
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(POLICY.forbidden(name))
                result = subprocess.run(["git", "check-ignore", "--no-index", "-q", name],
                                        cwd=ROOT, check=False)
                self.assertEqual(result.returncode, 0)

    def test_supplied_public_examples_and_code_remain_allowed(self):
        for name in ("data/README.md", "evaluation/gt/BAR-ATH_possession_gt_public.csv",
                     "evaluation/results/baseline_smooth50.csv", ".env.example",
                     "possession/pipeline.py", "configs/input-v1.json"):
            self.assertFalse(POLICY.forbidden(name))
        self.assertTrue(POLICY.forbidden("evaluation/results/baseline_private.csv"))
        self.assertTrue(POLICY.forbidden("BAR-ATH_possession_gt.csv"))


if __name__ == "__main__":
    unittest.main()
