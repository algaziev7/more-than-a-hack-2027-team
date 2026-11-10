"""Local-only: why do frames with E4 tracking evidence fall below the decoder cutoff?

Prints aggregate counts and shares only. Run on the restricted match locally and
keep the output out of Git, chat and hosted AI tools.
"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from possession.data import load_match  # noqa: E402
from possession.features import build_features, reliability_breakdown  # noqa: E402
from scripts.predict import load_config  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="versioned JSON configuration")
    parser.add_argument("--data-dir", help="bundle root; defaults to MTAH_DATA_DIR or ./data")
    parser.add_argument("--cutoff", type=float, default=0.25,
                        help="decoder team_reliability_min to test against")
    args = parser.parse_args(argv)
    config = load_config(args.config) if args.config else None
    match = load_match(data_dir=args.data_dir, config=config)
    counts = reliability_breakdown(build_features(match, config=config), args.cutoff)
    total = max(counts["tracking_frames"], 1)
    for name, count in counts.items():
        print("{:>16}: {:>8}  ({:.1%} of tracking frames)".format(name, count, count / total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
