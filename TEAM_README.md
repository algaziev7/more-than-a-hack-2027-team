# Team possession pipeline

E1 inputs, E4 tracking features and E3 combined priors are merged on main.
This E5 branch adds their wiring to `possession.state_machine.decode`, synthetic
CI and private reproducibility manifests. E2's decoder remains in
[PR #6](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/6).
Until a reviewed decoder is integrated, prediction exits before opening assets.
There is no complete team submission or measured accuracy improvement yet.

## Asset-free checks

Use Python 3.12 and run from the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-team.lock
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_setup.py
.venv/bin/python -m tabnanny possession scripts tests
.venv/bin/python .github/check_repository.py
git diff --check
```

On Windows use `py -3.12 -m venv .venv`, then `.venv\Scripts\python.exe`.
CI runs these synthetic checks on Ubuntu and Windows without assets or secrets.
Tests explicitly skip two real-decoder integration cases until E2 exists;
the wiring/error-path tests still run. An E2 review-branch overlay was checked
separately; see [Goblin's handoff](docs/team/owners/goblin.md) for exact evidence.

## Local prediction after E2 integration

Set `MTAH_DATA_DIR` on your laptop to the licensed root containing `tactical/`
and `broadcast/`. Follow [E1 setup](docs/team/SETUP.md) for local data checks.
Do not send assets, extracts, predictions or private run records to hosted AI.

```bash
.venv/bin/python scripts/predict.py --config configs/input-v1.json --output runs/dev/team.csv
.venv/bin/python scripts/check_solution.py runs/dev/team.csv
```

The CLI seeds Python/NumPy and exports E5's `Prediction` through E1's atomic
writer. `data.load_tags=false` disables tags; absent tags also work. E3 can
still derive motion clues without tags. `dead_ball.enabled=false` disables
motion priors while retaining tagging clues. Missing observations remain missing.
The pipeline passes the full config to each owner, checks stage contracts and
frame alignment, and rejects labels other than X outside the half masks.
It does not repair or smooth decoder output.

To save an exact output plus its private run manifest in one Python process:

```python
import random
import numpy as np
from scripts.predict import load_config
from possession.pipeline import predict_match
from possession.export import write_submission
from possession.run_manifest import write_run_manifest

config = load_config("configs/input-v1.json")
seed = config.get("seed", 0)
random.seed(seed)
np.random.seed(seed)
prediction = predict_match(config=config)  # resolves MTAH_DATA_DIR locally
output = write_submission(prediction, "runs/dev/team.csv")
write_run_manifest(prediction, output, "runs/dev/manifest.json")
```

The manifest records commit, tracked-worktree state, execution-source hashes,
canonical config/hash, input content hashes, dependency/Python versions, seed,
pipeline runtime, output SHA-256 and checks actually performed. Runtime excludes
manifest collection, export and validation. Source archives explicitly have no
Git identity. Only `write_run_manifest` adds official-validation and exact-byte
checks, after verifying the full-length CSV against the Prediction. E2's
diagnostics remain alongside `prediction.diagnostics["run_manifest"]`.
Manifests are private local artifacts; no input paths or arrays are serialized.

## Review and release

Read [current context](docs/team/CONTEXT.md), [interfaces](docs/team/INTERFACES.md)
and your [owner handoff](docs/team/owners/) before changes. E1 reviews E5.
Existing shared contracts and module settings are unchanged. E1 should review
the additional local diagnostic key and manifest helper; E2/E3/E4 should review
the wiring and combined synthetic evidence before integration.

The [technical draft](docs/team/TECHNICAL_DOCUMENT.md) describes actual modules
and pending decisions. Use the [release procedure](docs/team/RELEASE.md) for
the second-laptop hash comparison and final package. Keep experiment provenance
in [an experiment record](docs/team/experiments/TEMPLATE.md). Synthetic tests
establish correctness on invented inputs; full-match spellF1 remains unverified.
