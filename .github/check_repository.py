"""Filename-only CI guard. Never open assets, extracts, or private reports."""

from pathlib import PurePosixPath
import subprocess


def forbidden(name):
    path = PurePosixPath(name)
    if path.parts[0] in {"data", "artifacts", "runs", ".local"}:
        return name != "data/README.md"
    if path.name == ".env" or path.name.startswith(".env."):
        return path.name != ".env.example"
    if path.suffix.lower() in {".npz", ".npy", ".pkl", ".pickle", ".mp4",
                               ".mov", ".mkv", ".gzip", ".pl3container"}:
        return True
    if path.name.endswith(("_atd.txt", "_atd.xml", "_smart_tagging.xml",
                           "_possession_gt.csv", "_possession_gt_meta.json",
                           "_possession_gt_reference.csv")):
        return True
    if path.parent.as_posix() == "evaluation/results" and path.suffix == ".csv":
        return path.name not in {"baseline_raw.csv", "baseline_smooth25.csv",
                                 "baseline_smooth50.csv", "baseline_smooth125.csv"}
    return False


if __name__ == "__main__":
    result = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
    names = result.stdout.decode("utf-8").split("\0")
    if any(forbidden(name) for name in names if name):
        raise SystemExit("Tracked local artifacts detected; inspect Git filenames locally.")
    print("Tracked-file artifact check passed (filenames only).")
