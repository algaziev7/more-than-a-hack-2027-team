"""Deterministic UTF-8 submission export; invalid predictions never replace output."""

import os
from pathlib import Path
import tempfile

from games import GAME, GAMES
from possession.contracts import Prediction


def write_submission(prediction, path, *, n_expected=None):
    """Write exact frame,label CSV bytes atomically, returning the output Path.

    Default length is the published tactical frame count. A smaller explicit
    n_expected is supported for synthetic tests only. Labels are never coerced.
    """
    if not isinstance(prediction, Prediction):
        raise TypeError("prediction must be a Prediction")
    prediction.validate()
    expected = GAMES[GAME]["n_video_frames"] if n_expected is None else n_expected
    if type(expected) is not int or expected <= 0 or len(prediction.labels) != expected:
        raise ValueError("prediction length must equal the expected tactical frame count")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("frame,label\n")
            handle.writelines(f"{frame},{label}\n" for frame, label in enumerate(prediction.labels))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
