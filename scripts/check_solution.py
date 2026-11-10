"""Run the official format validator on the exact submission CSV."""

from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    validator = Path(__file__).resolve().parents[1] / "evaluation" / "validate_submission.py"
    sys.exit(subprocess.call([sys.executable, str(validator), *sys.argv[1:]]))
