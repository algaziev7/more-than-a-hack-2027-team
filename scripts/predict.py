"""E1 invocation layer. E5 supplies possession.pipeline.predict_match."""

import argparse
import importlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from possession.data import bundle_root, validate_config  # noqa: E402
from possession.export import write_submission  # noqa: E402


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("configuration contains duplicate JSON keys")
        result[name] = value
    return result


def load_config(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            config = json.load(handle, object_pairs_hook=_object)
    except json.JSONDecodeError:
        raise ValueError("configuration is not valid JSON") from None
    return validate_config(config)


def run_prediction(data_dir, config, output):
    config = validate_config(config)
    try:
        pipeline = importlib.import_module("possession.pipeline")
    except ModuleNotFoundError as exc:
        if exc.name != "possession.pipeline":
            raise
        raise RuntimeError(
            "E5 integration is not installed: possession.pipeline.predict_match is required; "
            "run scripts/check_setup.py for the synthetic infrastructure smoke test") from None
    predict_match = getattr(pipeline, "predict_match", None)
    if not callable(predict_match):
        raise RuntimeError("E5 pipeline must expose predict_match(data_dir, config)")
    seed = config.get("seed", 0)
    random.seed(seed)
    np.random.seed(seed)
    prediction = predict_match(data_dir=bundle_root(data_dir), config=config)
    return write_submission(prediction, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="versioned JSON configuration")
    parser.add_argument("--data-dir", help="bundle root; defaults to MTAH_DATA_DIR or ./data")
    parser.add_argument("--output", required=True, help="output CSV (use ignored runs/)")
    args = parser.parse_args(argv)
    try:
        output = run_prediction(args.data_dir, load_config(args.config), args.output)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"prediction failed: {exc}\n")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
