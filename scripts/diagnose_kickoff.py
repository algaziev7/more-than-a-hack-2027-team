"""Human-terminal-only kickoff diagnostics; restricted reports stay local.

Never run this script on competition inputs through hosted AI tools.
It saves aggregate detector stages without printing match diagnostics.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from possession.data import load_match  # noqa: E402
from possession.dead_ball import summarize_kickoff_diagnostics  # noqa: E402
from possession.features import build_features  # noqa: E402
from scripts.predict import load_config  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/input-v1.json",
                        help="use the actual prediction run's JSON config")
    parser.add_argument("--data-dir", help="bundle root; defaults to MTAH_DATA_DIR or ./data")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    match = load_match(data_dir=args.data_dir, config=config)
    features = build_features(match, config=config)
    report = summarize_kickoff_diagnostics(match, features=features, config=config)
    destination = ROOT / "runs" / "kickoff-gates.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Saved runs/kickoff-gates.json. Inspect locally; do not share the report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
