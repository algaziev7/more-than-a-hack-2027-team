"""E1 environment smoke test and opt-in local match inventory.

Without --check-data this reads only synthetic fixtures and public schemas.
Private inventories/check results go to ignored .local/, never stdout.
"""

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from games import GAME, GAMES, asset_paths  # noqa: E402
from possession.contracts import Prediction  # noqa: E402
from possession.data import bundle_root, load_match, sha256_file  # noqa: E402
from possession.export import write_submission  # noqa: E402


def smoke_test():
    """Check all contracts and a full-length invented CSV with the official validator."""
    from evaluation.possession_metrics import read_label_csv, validate_submission
    from tests.fixtures import neutral_features, neutral_priors, synthetic_match

    match = synthetic_match()
    neutral_features(match)
    neutral_priors(match)
    n = GAMES[GAME]["n_video_frames"]
    # Deliberately invented pattern; neither a model nor a candidate submission.
    prediction = Prediction(np.resize(np.array(list("HADX")), n))
    with tempfile.TemporaryDirectory() as directory:
        first = write_submission(prediction, Path(directory) / "one.csv")
        second = write_submission(prediction, Path(directory) / "two.csv")
        if sha256_file(first) != sha256_file(second):
            raise ValueError("synthetic export is not deterministic")
        reason = validate_submission(read_label_csv(first), n)
        if reason is not None:
            raise ValueError(f"synthetic CSV rejected by official validator: {reason}")
    return {"contracts": "pass", "deterministic_export": "pass", "official_validator": "pass"}


def inspect_video(path):
    """Optional complete reference decode count, without exposing any images."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is required only for --check-video")
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=nb_read_frames,avg_frame_rate,width,height", "-of", "json",
        str(path),
    ], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("ffprobe could not decode the tactical video; inspect it locally")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        numerator, denominator = map(int, stream["avg_frame_rate"].split("/"))
        count = int(stream["nb_read_frames"])
        fps = numerator / denominator
        shape = (stream["width"], stream["height"])
    except (ValueError, KeyError, IndexError, ZeroDivisionError, TypeError):
        raise ValueError("ffprobe did not return a usable video frame count") from None
    if count != GAMES[GAME]["n_video_frames"] or fps != GAMES[GAME]["fps"] or shape != (1920, 1080):
        raise ValueError("decoded tactical video disagrees with the published reference")
    return {"frame_count": count, "fps": fps, "width": shape[0], "height": shape[1]}


def check_data(data_dir, *, inventory=False, check_video=False):
    root = bundle_root(data_dir)
    match = load_match(root, {"schema_version": 1, "data": {"cache": False}})
    report = {
        "tracking": "validated every frame ID, slot mapping, coordinate and observation mask",
        "metadata": match.metadata,
    }
    if inventory:
        report["assets"] = {}
        for source in ("tactical", "broadcast"):
            for name, filename in asset_paths(data_dir=root, source=source).items():
                path = Path(filename)
                record = {"present": path.is_file(), "filename": path.name}
                if path.is_file():
                    record.update(size_bytes=path.stat().st_size, sha256=sha256_file(path))
                report["assets"][f"{source}/{name}"] = record
    if check_video:
        report["video"] = inspect_video(asset_paths(data_dir=root)["video"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-data", action="store_true", help="read restricted assets locally")
    parser.add_argument("--data-dir", help="bundle root, or use MTAH_DATA_DIR")
    parser.add_argument("--inventory", action="store_true", help="hash all assets, including videos")
    parser.add_argument("--check-video", action="store_true", help="count tactical frames using ffprobe")
    args = parser.parse_args(argv)
    if (args.inventory or args.check_video or args.data_dir) and not args.check_data:
        parser.error("--data-dir, --inventory and --check-video require --check-data")
    try:
        report = {"python": platform.python_version(), "platform": platform.system(),
                  "dependencies": {name: importlib.metadata.version(name) for name in
                                   ("numpy", "pandas", "python-dateutil", "six", "tzdata")},
                  "smoke": smoke_test()}
        if args.check_data:
            report["data"] = check_data(args.data_dir, inventory=args.inventory, check_video=args.check_video)
            destination = ROOT / ".local" / "setup.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("Local data checks passed; private report saved to .local/setup.json.")
        else:
            print("Synthetic contracts, deterministic full-length export, and official validation passed.")
            print("No match assets were read. Use --check-data locally to verify your bundle.")
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"setup check failed: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
