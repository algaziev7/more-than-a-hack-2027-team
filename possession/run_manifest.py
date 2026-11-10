"""Local reproducibility records; never print or publish match-run manifests."""

import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

from possession.contracts import Prediction
from possession.data import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def _git(*args):
    try:
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                                text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def capture_run(config):
    """Record public code/config identity, without reading match data or GT."""
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False)
    versions = {}
    for name in ("numpy", "pandas", "python-dateutil", "six", "tzdata"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    status = _git("status", "--porcelain", "--untracked-files=no")
    # Hash execution sources as well as recording HEAD: a dirty checkout or a
    # source archive must never be mistaken for an exact committed release.
    sources = [ROOT / "games.py", ROOT / "scripts" / "predict.py",
               ROOT / "evaluation" / "possession_metrics.py",
               ROOT / "requirements-team.lock"]
    sources.extend(sorted((ROOT / "possession").glob("*.py")))
    return {
        "manifest_version": 1,
        "code_commit": _git("rev-parse", "HEAD"),
        "tracked_worktree_dirty": None if status is None else bool(status),
        "source_sha256": {path.relative_to(ROOT).as_posix(): sha256_file(path)
                          for path in sources if path.is_file()},
        "config": copy.deepcopy(config),
        "config_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "seed": config.get("seed", 0),
        "python": platform.python_version(),
        "platform": platform.system(),
        "dependencies": versions,
    }


def write_run_manifest(prediction, output, path):
    """Validate the exact exported CSV, then atomically save its private record.

    This reads only the supplied output, never any ground truth. It verifies
    byte-for-byte agreement with the Prediction and the official full-length
    format before claiming a check passed. Export remains E1's responsibility.
    """
    from evaluation.possession_metrics import read_label_csv, validate_submission
    from games import GAME, GAMES

    if not isinstance(prediction, Prediction):
        raise TypeError("prediction must be a Prediction")
    prediction.validate()
    run = prediction.diagnostics.get("run_manifest")
    if not isinstance(run, dict) or run.get("manifest_version") != 1:
        raise ValueError("prediction needs a pipeline run_manifest")
    output, path = Path(output), Path(path)
    if output.resolve() == path.resolve():
        raise ValueError("manifest must not overwrite the submission CSV")
    expected = hashlib.sha256(b"frame,label\n")
    for frame, label in enumerate(prediction.labels):
        expected.update(f"{frame},{label}\n".encode("utf-8"))
    checksum = sha256_file(output)
    if checksum != expected.hexdigest():
        raise ValueError("exported CSV does not match this prediction")
    reason = validate_submission(read_label_csv(output), GAMES[GAME]["n_video_frames"])
    if reason is not None:
        raise ValueError("exported CSV failed official format validation")
    if sha256_file(output) != checksum:
        raise ValueError("exported CSV changed during validation")
    record = copy.deepcopy(run)
    record["output_sha256"] = checksum
    record["checks"].update(exact_prediction_bytes="pass", official_validator="pass")
    encoded = json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
