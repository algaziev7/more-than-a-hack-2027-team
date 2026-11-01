# E1 setup and input contract

This branch implements data infrastructure. It does not contain a possession
model or E5's integrated pipeline. The public five minutes are only a pipeline
sanity check; do not use their scores for training, tuning, or model selection.

Validation status (2026-10-25): Azamat reported that the real-data
`--check-data` command passed after parser fix `cfc7fac`. This verifies basic
tactical input loading on his laptop. Video decoding, the complete inventory,
baseline regeneration, other laptops, and E5 prediction integration remain
separate checks. The private report was not read by the assistant or committed.

## Environment and synthetic checks

The verified environment is Python 3.12.12 on macOS arm64. Use Python 3.12 on
other laptops and record the exact patch version in the local setup report.
Other operating systems have not yet been verified. The organiser's original
requirements and optional notebook environment are unchanged.

From the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-team.lock
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_setup.py
.venv/bin/python evaluation/run_evaluation.py
```

On Windows use `py -3.12 -m venv .venv` and `.venv\Scripts\python.exe`
in place of `.venv/bin/python`.

`check_setup.py` exercises all four contracts and writes two full-length,
invented CSVs into a temporary directory. Their bytes must match, and the
official validator must accept them. They are deleted after the check. No match
assets, ground truth, model, video decoder, or GPU are needed for this smoke test.
The separate scorer command reads only committed public GT and baseline CSVs;
it checks the environment, not the quality of a team model.

## Restricted-data checks: run on your laptop

Set the root containing `tactical/` and `broadcast/`; pointing directly at
`tactical/` is an error. Do not commit the path or put it in shared config.

```bash
export MTAH_DATA_DIR='/absolute/path/to/extracted/bundle'
.venv/bin/python scripts/check_setup.py --check-data
```

PowerShell: `$env:MTAH_DATA_DIR = 'D:\path\to\bundle'`.
Alternatively pass `--data-dir` to the check or prediction command.

This checks every ordered tracking ID, slot membership, coordinate validity,
metre conversion, and observation masks. It writes private results and asset
digests to ignored `.local/setup.json`. Do not paste that report, tracking
rows, frames, or derived arrays into hosted AI tools or commit them.

For a full filename/size/SHA-256 inventory and reference-video decode count:

```bash
.venv/bin/python scripts/check_setup.py --check-data --inventory --check-video
```

This may take several minutes: it hashes both videos and decodes/counts the
tactical frames. `ffprobe` is needed only for `--check-video`; the check requires
199,319 decoded tactical frames, 25 fps and 1920×1080. Inventory reports missing
optional assets explicitly. The initial loader needs only tactical ATD XML/TXT;
missing Smart Tagging yields an empty event list, recorded in metadata.

Check baseline regeneration locally without replacing the shipped CSVs:

```bash
.venv/bin/python starter/baseline.py --out runs/setup/baselines-a
.venv/bin/python starter/baseline.py --out runs/setup/baselines-b
```

Compare each generated file's SHA-256 across both directories and against the
committed reference using a local tool. A mismatch is a setup investigation,
not permission to tune against public GT. Keep outputs and reports local.

## APIs for the other owners

`possession.contracts` exports `MatchData`, `FeatureData`, `PriorData`,
`Prediction`, `Event`, and `SCHEMA_VERSION = 1`. Constructors validate array
shapes, dtypes, masks, label sets and evidence ranges without mutating inputs.
These are concrete implementations of `INTERFACES.md`, awaiting consumer review.

```python
from possession.data import load_match

match = load_match(config={"schema_version": 1, "data": {"cache": True}})
# match.frame: int64[N], match.half: int8[N], 0 excluded / 1 first / 2 second
# match.ball_xy_m: float[N,2], match.players_xy_m: float[N,P,2]
# match.ball_observed: bool[N], match.player_observed: bool[N,P]
# match.slot_team: H/A[P], match.events: list[dict]
```

Frame IDs must be exactly 1..N in the raw file; the loader maps them to 0..N-1.
The published half intervals come from `games.half_video_blocks`. They include
the graded pre-kickoff portion of the second half; the loader assigns no
possession state. Normalized coordinates are scaled by `games.py` pitch size.
Positions beyond the pitch are retained. Missing positions remain NaN pairs;
zero is a valid observation. No interpolation or imputation is performed.
`ball_speed_mps` uses the ATD third field in m/s only when the ball position is
observed; `np.isfinite` is its validity mask. Raw speed placeholders may exist
even when coordinates are missing. Those speeds are masked to NaN so they do
not become observed motion evidence. Missing speed may coexist with an observed
ball position. Missing player positions likewise do not require a missing raw
speed field.

Events retain original code/tag strings and overlaps. Seconds use
`round(seconds * fps)`, including ties to even. Intervals are clipped to
`[0,N]`, remain half-open, and empty intervals are discarded. Reversed or
nonfinite source times fail validation. Repeated tag groups use the starter's
last-value-wins convention. Team semantics belong to E3, not this loader.

Synthetic examples are available to all owners:

```python
from tests.fixtures import (
    synthetic_match, neutral_features, neutral_priors, synthetic_prediction,
)

match = synthetic_match()
features = neutral_features(match)
priors = neutral_priors(match)
prediction = synthetic_prediction()
```

`FeatureData.features` and `.validity` are identically keyed dictionaries of
float[N] arrays and bool[N] masks. `PriorData.diagnostic_flags`, when provided,
is an integer[N] array. `Prediction.labels` is a one-dimensional numpy array
containing only H/A/D/X, with optional `.diagnostics`. Almaz's new
`build_tagging_priors(match.events, len(match.frame))` returns `PriorData`
directly. If tagging signals are already loaded as lists, use
`to_prior_data(signals)` from `possession.tagging`. See [TAGGING.md](TAGGING.md).
E5 still checks that all modules use the same frames, and that excluded frames
receive X labels.

The new stoppage-prior branch also offers
`possession.dead_ball.build_priors(match, features=None, config=None)`. It keeps
the tagging clues and adds conservative motion-based evidence in the same
PriorData type. See [DEAD_BALL.md](DEAD_BALL.md) for rules, timing, and limits.
It uses the existing locked dependencies and does not need video or new packages.

## Configuration, cache, export and invocation

`configs/input-v1.json` is an input-layer example, **not a final model config**.
Shared config fields are integer `schema_version: 1`, integer seed in
`[0,2**32)`, and boolean `data.load_tags` (default true) / `data.cache` (default
false). Other module sections pass through unchanged. Configurations must
contain finite JSON values, string object keys, and no local absolute paths.
The CLI additionally rejects duplicate JSON keys.

Caches default to ignored `artifacts/cache/`. A local `cache_dir=` keyword can
override that directory without adding a laptop path to config. Keys include
input content hashes, config, schema, game constants, and loader/contract source
hashes. Numeric arrays and JSON are stored with pickle disabled. Writes are
atomic; unreadable or incompatible entries are rebuilt. Input files changing
during a load cause an error rather than a mixed snapshot. Caches are private,
disposable artifacts, never shared context.

```python
from possession.export import write_submission

write_submission(prediction, "runs/final/team_name.csv")
# Requires exactly 199319 labels; smaller explicit n_expected is for tests only.
```

Export validates before writing, uses UTF-8 with LF newlines, and atomically
replaces the target. Invalid predictions preserve any existing output. No
label coercion, extra index, blanks, or timestamps are introduced.

Once E5 implements `possession.pipeline.predict_match(data_dir, config)`:

```bash
.venv/bin/python scripts/predict.py --config configs/input-v1.json --output runs/dev/prediction.csv
.venv/bin/python evaluation/validate_submission.py runs/dev/prediction.csv
```

The CLI sets Python/NumPy seeds, resolves the local bundle path, calls E5, and
exports its `Prediction`. Until E5 is available it exits with a clear error and
writes no prediction. It supplies no substitute model. The prediction package
does not import GT or the scorer. E4 owns checking the final file, and E5 owns
pipeline integration and independent reproduction on another laptop.
