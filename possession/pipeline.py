"""Thin E5 wiring; possession policy remains in the E2 decoder."""

import copy
import importlib
import time

import numpy as np

from possession.contracts import FeatureData, MatchData, Prediction, PriorData
from possession.data import load_match, validate_config
from possession.dead_ball import build_priors
from possession.features import build_features
from possession.run_manifest import capture_run

# Every top-level section some stage reads. A misspelt one would otherwise be silently ignored.
CONFIG_SECTIONS = {"schema_version", "seed", "data", "tagging", "dead_ball", "state_machine"}


def _decoder():
    try:
        module = importlib.import_module("possession.state_machine")
    except ModuleNotFoundError as exc:
        if exc.name != "possession.state_machine":
            raise
        raise RuntimeError(
            "E2 decoder is unavailable: integrate the reviewed "
            "possession.state_machine.decode before running predictions; "
            "scripts/check_setup.py remains available without match data"
        ) from None
    decode = getattr(module, "decode", None)
    if not callable(decode):
        raise RuntimeError("E2 must expose possession.state_machine.decode")
    return decode


def predict_match(data_dir=None, config=None) -> Prediction:
    """Load -> tracking features -> combined priors -> decode, without exporting.

    The E1 CLI owns paths, seeding and CSV export. Missing/disabled tags yield
    empty events in E1 and remain supported by E3. A missing decoder is an
    explicit error before any asset is opened; there is no placeholder model.
    Each stage receives the full JSON config, with no new config sections.
    """
    config = copy.deepcopy(validate_config(config))
    unknown = sorted(set(config) - CONFIG_SECTIONS)
    if unknown:
        raise ValueError("unknown configuration sections {}; expected only {}".format(
            unknown, sorted(CONFIG_SECTIONS)))
    decode = _decoder()
    # Capture code identity before execution; manifests are private diagnostics.
    run = capture_run(config)
    started = time.perf_counter()
    match = load_match(data_dir=data_dir, config=config)
    if not isinstance(match, MatchData):
        raise TypeError("E1 loader must return MatchData")
    match.validate()

    features = build_features(match, config=config)
    if not isinstance(features, FeatureData):
        raise TypeError("E4 must return FeatureData")
    features.__post_init__()
    if not np.array_equal(features.frame, match.frame):
        raise ValueError("features and match must use the same frame timeline")

    priors = build_priors(match, features=features, config=config)
    if not isinstance(priors, PriorData):
        raise TypeError("E3 must return PriorData")
    priors.__post_init__()
    if len(priors.dead_evidence) != len(match.frame):
        raise ValueError("priors and match must use the same frame timeline")

    prediction = decode(match, features, priors, config=config)
    if not isinstance(prediction, Prediction):
        raise TypeError("E2 must return Prediction")
    prediction.validate()
    if len(prediction.labels) != len(match.frame):
        raise ValueError("prediction and match must use the same frame timeline")
    if np.any(prediction.labels[match.half == 0] != "X"):
        raise ValueError("E2 must return X outside the supplied half intervals")
    # A half labelled entirely D (e.g. a half-start gate that never opened) is never a real
    # result: fail rather than export it. Uses only contract fields; the message has no match data.
    for half in np.unique(match.half[match.half > 0]):
        if np.all(prediction.labels[match.half == half] == "D"):
            raise RuntimeError("half {} is labelled entirely D, so no submission was written; "
                               "decode locally and check diagnostics['period_starts']"
                               .format(int(half)))

    run.update(
        runtime_s=time.perf_counter() - started,
        input_sha256=copy.deepcopy(match.metadata.get("asset_sha256", {})),
        frame_count=len(match.frame),
        checks={"shared_contracts": "pass", "frame_alignment": "pass",
                "excluded_frames": "pass"},
    )
    # Preserve E2 reasons without changing the object returned by the decoder.
    diagnostics = dict(prediction.diagnostics)
    diagnostics["run_manifest"] = run
    return Prediction(prediction.labels.copy(), diagnostics)
