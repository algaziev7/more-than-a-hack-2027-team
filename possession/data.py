"""Strict tactical input loader with an optional local, content-addressed cache.

Only raw ATD and optional Smart Tagging are read. Video, homography, kloppy and
ground truth are not required. Exceptions never include a tracking row.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from games import GAME, GAMES, asset_paths, half_video_blocks
from possession.contracts import MatchData, SCHEMA_VERSION

# How each period starts, from the documented grading semantics (FAQ.md, DATA.md): half 1 is
# graded from its own kickoff, half 2 from before its kickoff. A declared property of the period,
# never a frame number; E2 keeps an await_start period dead until E3 confirms play started.
PERIOD_START = {"1": "live_at_entry", "2": "await_start"}

ROOT = Path(__file__).resolve().parents[1]


def validate_config(config=None):
    """Check shared invocation fields; other owners retain their config sections."""
    config = {} if config is None else config
    if not isinstance(config, dict):
        raise ValueError("configuration must be a JSON object")
    def check_values(value):
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("configuration object keys must be strings")
            for item in value.values():
                check_values(item)
        elif isinstance(value, list):
            for item in value:
                check_values(item)
        elif isinstance(value, str) and (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()):
            raise ValueError("local absolute paths belong in CLI/environment, not configuration")
    check_values(config)
    # Also rejects nonfinite floats, sets, arrays, and unserialisable objects.
    try:
        json.dumps(config, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError):
        raise ValueError("configuration must contain only finite JSON values") from None
    version = config.get("schema_version", SCHEMA_VERSION)
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError("unsupported configuration schema_version")
    seed = config.get("seed", 0)
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    options = config.get("data", {})
    if not isinstance(options, dict) or set(options) - {"load_tags", "cache"}:
        raise ValueError("data options are load_tags and cache only; paths belong in CLI/environment")
    if any(type(value) is not bool for value in options.values()):
        raise ValueError("data.load_tags and data.cache must be booleans")
    return config


def bundle_root(data_dir=None):
    """Resolve the environment at call time, including after games was imported."""
    value = data_dir if data_dir is not None else os.environ.get("MTAH_DATA_DIR")
    root = Path(value).expanduser() if value else ROOT / "data"
    if not root.is_dir():
        raise FileNotFoundError(
            "match bundle directory is missing; set MTAH_DATA_DIR or pass --data-dir "
            "to the root containing tactical/ and broadcast/")
    return root.resolve()


def read_slot_teams(meta_path):
    """Return slot teams in XML Player order, following the starter convention."""
    try:
        root = ET.parse(meta_path).getroot()
    except (ET.ParseError, OSError):
        raise ValueError("cannot read ATD metadata XML") from None
    teams = list(root.iter("Team"))
    ids = [team.get("id") for team in teams]
    if len(ids) != 2 or None in ids or len(set(ids)) != 2:
        raise ValueError("ATD metadata must define exactly two distinct team IDs")
    mapping = {ids[0]: "H", ids[1]: "A"}
    players = list(root.iter("Player"))
    if not players:
        raise ValueError("ATD metadata has no track slots")
    if any(player.get("teamId") not in mapping for player in players):
        raise ValueError("ATD metadata contains an unknown slot team")
    return np.array([mapping[player.get("teamId")] for player in players], dtype="<U1")


def _observation(group):
    values = group.strip().split(",")
    if len(values) != 3:
        raise ValueError("ATD observations must have x,y,speed fields")
    try:
        x, y, speed = map(float, values)
    except ValueError:
        raise ValueError("ATD observation has a nonnumeric field") from None
    if np.isnan(x) and np.isnan(y):
        # ATD may retain a filled/stale speed when the position is missing.
        # Such a value cannot establish observed motion; mask it canonically.
        return np.nan, np.nan, np.nan
    if not np.isfinite([x, y]).all():
        raise ValueError("ATD position must be a finite pair or a NaN pair")
    if not (np.isnan(speed) or (np.isfinite(speed) and speed >= 0)):
        raise ValueError("ATD speed must be nonnegative or NaN")
    return x, y, speed


def read_tracking(raw_path, slot_team, n_frames, pitch_m):
    """Read every ID strictly in order. Return metres and usable ball speed (m/s).

    Partial coordinates and malformed/truncated/duplicate/reordered records are
    errors. Coordinates outside the pitch are preserved, useful for stoppages.
    Numeric speeds accompanying missing coordinate pairs are ignored; canonical
    speed is NaN there, independent of the raw placeholder value.
    This function also accepts small frame counts for synthetic tests.
    """
    if type(n_frames) is not int or n_frames <= 0:
        raise ValueError("n_frames must be a positive integer")
    if len(slot_team) == 0 or not np.isin(slot_team, ["H", "A"]).all():
        raise ValueError("tracking needs a known team for every slot")
    scale = np.asarray(pitch_m, dtype=float)
    if scale.shape != (2,) or not np.all(np.isfinite(scale) & (scale > 0)):
        raise ValueError("pitch_m must contain two finite positive dimensions")
    ball = np.full((n_frames, 2), np.nan)
    players = np.full((n_frames, len(slot_team), 2), np.nan)
    speed = np.full(n_frames, np.nan)
    count = 0
    with open(raw_path, encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index >= n_frames:
                raise ValueError("ATD has more records than the tactical frame count")
            parts = line.strip().split(":")
            if len(parts) != 3:
                raise ValueError("ATD record must contain frame:players:ball")
            try:
                frame_id = int(parts[0])
            except ValueError:
                raise ValueError("ATD frame ID must be an integer") from None
            if frame_id != index + 1:
                raise ValueError("ATD frame IDs must be exactly 1..N in file order")
            groups = parts[1].split(";")
            if len(groups) != len(slot_team):
                raise ValueError("ATD slot count disagrees with metadata")
            for slot, group in enumerate(groups):
                x, y, _ = _observation(group)
                players[index, slot] = (x, y)
            x, y, speed[index] = _observation(parts[2])
            ball[index] = (x, y)
            count += 1
    if count != n_frames:
        raise ValueError("ATD record count disagrees with the tactical frame count")
    ball *= scale
    players *= scale
    return ball, players, speed


def read_events(path, n_frames, fps):
    """SportsCode parsing mirrors the starter; preserve dictionaries and overlaps.

    Round seconds*fps with Python round (ties to even), clip to [0,N], discard
    empty spans. A reversed or malformed source interval is rejected.
    """
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        raise ValueError("cannot read Smart Tagging XML") from None
    events = []
    for instance in root.iter("instance"):
        try:
            start_s = float(instance.findtext("start"))
            end_s = float(instance.findtext("end"))
        except (TypeError, ValueError):
            raise ValueError("tag intervals need numeric start and end seconds") from None
        if not np.isfinite([start_s, end_s]).all() or end_s < start_s:
            raise ValueError("tag interval is nonfinite or reversed")
        start = max(0, min(n_frames, round(start_s * fps)))
        end = max(0, min(n_frames, round(end_s * fps)))
        if start >= end:
            continue
        events.append({
            "start_frame": start, "end_frame": end, "start_s": start_s, "end_s": end_s,
            "code": instance.findtext("code") or "",
            "tags": {label.findtext("group") or "": label.findtext("text") or ""
                     for label in instance.findall("label")},
        })
    return events


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cache_key(paths, config):
    assets = {key: sha256_file(path) for key, path in paths.items()}
    identity = {
        "schema_version": SCHEMA_VERSION, "config": config, "game": GAMES[GAME],
        "assets": assets,
        "loader": sha256_file(Path(__file__)),
        "contracts": sha256_file(Path(__file__).with_name("contracts.py")),
    }
    encoded = json.dumps(identity, sort_keys=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), assets


def _write_cache(path, match):
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {name: getattr(match, name) for name in (
        "frame", "half", "ball_xy_m", "ball_observed", "players_xy_m",
        "player_observed", "slot_team", "ball_speed_mps")}
    info = {"fps": match.fps, "pitch_m": match.pitch_m,
            "events": match.events, "metadata": match.metadata}
    # JSON and numeric arrays only. Never unpickle a local cache.
    arrays["info"] = np.array(json.dumps(info, sort_keys=True, allow_nan=False))
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with temporary.open("wb") as handle:
            np.savez_compressed(handle, **arrays)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_cache(path, key):
    with np.load(path, allow_pickle=False) as cached:
        info = json.loads(str(cached["info"]))
        if not isinstance(info, dict) or not isinstance(info.get("metadata"), dict):
            raise ValueError("cache metadata is malformed")
        if info["metadata"].get("cache_key") != key:
            raise ValueError("cache identity mismatch")
        return MatchData(**{name: cached[name].copy() for name in (
            "frame", "half", "ball_xy_m", "ball_observed", "players_xy_m",
            "player_observed", "slot_team", "ball_speed_mps")},
            fps=info["fps"], pitch_m=tuple(info["pitch_m"]),
            events=info["events"], metadata=info["metadata"])


def load_match(data_dir=None, config=None, *, cache_dir=None):
    """Load canonical tactical arrays. Optional cache_dir stays outside config.

    data.load_tags defaults true; an absent tags file yields an empty event list.
    data.cache defaults false; enabled caches live in ignored artifacts/cache/.
    No imputation is performed. Ball-speed validity is isfinite(ball_speed_mps).
    """
    config = validate_config(config)
    options = config.get("data", {})
    paths = {key: Path(value) for key, value in asset_paths(data_dir=bundle_root(data_dir)).items()}
    required = {key: paths[key] for key in ("atd_meta", "atd_raw")}
    if any(not path.is_file() for path in required.values()):
        raise FileNotFoundError(
            "tactical ATD metadata/raw files are missing; check MTAH_DATA_DIR or --data-dir "
            "against data/README.md (the root must contain tactical/)")
    tags_available = options.get("load_tags", True) and paths["smart_tagging"].is_file()
    if tags_available:
        required["smart_tagging"] = paths["smart_tagging"]
    key, assets = _cache_key(required, config)
    cache_path = None
    if options.get("cache", False):
        cache_path = Path(cache_dir) if cache_dir is not None else ROOT / "artifacts" / "cache"
        cache_path = cache_path / f"{key}.npz"
        if cache_path.is_file():
            try:
                return _read_cache(cache_path, key)
            except (ValueError, KeyError, TypeError, OSError, EOFError, zipfile.BadZipFile):
                # A corrupt/incompatible cache is rebuilt from the original assets.
                pass
    spec = GAMES[GAME]
    n = spec["n_video_frames"]
    slot_team = read_slot_teams(required["atd_meta"])
    ball, players, speed = read_tracking(required["atd_raw"], slot_team, n, spec["pitch"])
    half = np.zeros(n, dtype=np.int8)
    for number, start, last in half_video_blocks(GAME):
        half[max(0, start):min(n, last + 1)] = number
    events = read_events(required["smart_tagging"], n, spec["fps"]) if tags_available else []
    if any(sha256_file(path) != assets[name] for name, path in required.items()):
        raise ValueError("input assets changed during loading; retry with stable files")
    match = MatchData(
        frame=np.arange(n, dtype=np.int64), half=half, fps=spec["fps"],
        pitch_m=tuple(spec["pitch"]), ball_xy_m=ball,
        ball_observed=np.isfinite(ball).all(axis=1), players_xy_m=players,
        player_observed=np.isfinite(players).all(axis=2), slot_team=slot_team,
        ball_speed_mps=speed, events=events,
        metadata={"schema_version": SCHEMA_VERSION, "game": GAME, "source": "tactical",
                  "asset_sha256": assets, "cache_key": key, "tags_available": bool(tags_available),
                  "ball_speed_source": "raw ATD third field (m/s), masked when position is missing",
                  "ball_speed_validity": "isfinite(ball_speed_mps)", "imputed": False,
                  "period_start": dict(PERIOD_START)},
    )
    if cache_path is not None:
        _write_cache(cache_path, match)
    return match
