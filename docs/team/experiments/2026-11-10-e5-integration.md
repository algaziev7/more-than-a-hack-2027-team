# E5 synthetic integration checkpoint

- Owner: Goblin; branch `e5/pipeline-v1`; date 2026-11-10.
- Base: main `3197721`; candidate decoder:
  `9883b4da012b4ee9102da81c3c9425c50aac3f9b` from E2 PR #6.
- Config: defaults or explicit invented test settings; no tuning or selection.
- Purpose: verify wiring, missing-tag handling, contract failures, deterministic
  export, private manifest validation and compatibility with the unmerged decoder.
- Source: invented tracking/XML/evidence only; no labels from any match, no
  competition assets and no public answer file. No training was performed.
- Environment: Python 3.12.12/macOS arm64, existing `requirements-team.lock`.

## Measured results

`python -m unittest discover -s tests`: 127 discovered, 125 pass and 2 explicit
real-decoder skips on E5 alone. Main before E5: 111 pass. The two skipped tests
exercise actual E2 decoding; wiring tests use an explicitly test-only decoder.

A disposable source overlay adding only E2's module and its three test/helper
files: all 174 tests pass, no skips. This includes a fully invented 199,319-frame
pipeline output accepted by the official validator and exact-byte manifest check,
plus team swapping, half reset and repeated CSV export. E2 files were not added
to E5's branch. This is compatibility evidence, not a reviewed merge.

`python scripts/check_setup.py`, `python -m pip check`, `python -m tabnanny
possession scripts tests .github`, `git diff --check`, local Markdown-link/example
syntax checks and the filename-only repository guard passed. No data command in
the documentation was executed. Native Windows/Linux CI results are recorded in
the owner handoff after the branch is pushed.

## Reproduce the compatibility check

With the locked Python environment active, run this from the E5 checkout after
fetching E2's revision. It copies public code into a temporary directory, never
opens a data bundle and never modifies another owner's checkout:

```python
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

source = Path.cwd()
revision = "9883b4da012b4ee9102da81c3c9425c50aac3f9b"
with tempfile.TemporaryDirectory(prefix="mtah-e5-e2-") as directory:
    root = Path(directory)
    for name in ("possession", "tests", "scripts", "starter", ".github"):
        shutil.copytree(source / name, root / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.ipynb"))
    (root / "evaluation").mkdir()
    for name in ("possession_metrics.py", "validate_submission.py"):
        shutil.copyfile(source / "evaluation" / name, root / "evaluation" / name)
    for name in ("games.py", ".gitignore", "requirements-team.lock"):
        shutil.copyfile(source / name, root / name)
    for name in ("possession/state_machine.py", "tests/test_state_machine.py",
                 "tests/e2_scenarios.py", "tests/test_state_machine_validation.py"):
        result = subprocess.run(["git", "show", revision + ":" + name],
                                check=True, capture_output=True)
        (root / name).write_bytes(result.stdout)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                            cwd=root, check=False,
                            env=dict(os.environ, PYTHONPATH=str(root),
                                     MTAH_DATA_DIR="__synthetic_only__"))
    if result.returncode:
        raise SystemExit(result.returncode)
```

Decision: submit the thin integration increment for E1 review. Keep E2 as an
explicit dependency instead of copying its implementation or inventing fallback
labels. Independent second-laptop reproduction and full-match accuracy remain
unverified. Final candidate selection and restricted-data execution are separate
release work; no score improvement is claimed here.
