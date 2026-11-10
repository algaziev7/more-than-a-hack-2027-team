# Azamat — Data and infrastructure

- Owner: Azamat
- Status: E1 infrastructure merged in PR #2; Windows path fix verified synthetically, awaiting review
- Branch: e1/data-contract
- Reviewer: E5
- Owned files: possession/contracts.py; possession/data.py; possession/export.py; scripts/predict.py; environment files
- Current milestone: portability follow-up and preparation for E5 integration
- Last update: 2026-11-10

## Completed and verified

- Implemented version 1 MatchData, FeatureData, PriorData, Prediction and Event
  contracts in `possession/contracts.py`, with shared invented examples in
  `tests/fixtures.py`. Constructors check shapes, dtypes, masks and evidence.
- Implemented strict tactical ATD/XML input loading, metre conversion, exact
  frame-ID checks, optional tags, original event dictionaries, published half
  masks, and explicit missing positions/speed. No imputation and no GT access.
- Added content/config/schema/code-addressed local caches, safe numeric/JSON
  serialization, corruption recovery and atomic writes.
- Added deterministic validated CSV export and JSON/seeding/path invocation
  through `scripts/predict.py`. It delegates to E5's future `predict_match`;
  it does not supply a possession model.
- Created `.venv`; installed and verified exact core/scorer dependency versions
  in `requirements-team.lock` on Python 3.12.12 / macOS arm64.
- Added `scripts/check_setup.py`: asset-free synthetic smoke test, plus opt-in
  local bundle inventory and ffprobe reference-video verification. Private
  reports go to ignored `.local/`; caches to `artifacts/`.
- Added setup/reproduction instructions in `docs/team/SETUP.md` and concrete
  constructor notes in `INTERFACES.md`. Organiser code/baselines are unchanged.
- Corrected an overly strict raw-parser assumption after the user's local
  setup run failed: absent coordinates can coexist with a numeric speed field.
  Canonical position/speed remain NaN and observation masks remain false for
  such tracks. Added invented regression cases, including a cache round trip.
- Azamat reran the local real-data setup command after `cfc7fac` and reported
  `Local data checks passed; private report saved to .local/setup.json.`
  This confirms successful canonical tracking/tag loading on his laptop. The
  assistant did not read the private report or match contents.
- Refreshed the branch from main after Almaz's tagging PR #1 was merged. Kept
  Almaz's plain-language interface guide and added E1's concrete constructor
  details. Added a synthetic loader-to-tagging/PriorData compatibility check.
- PR #2 was merged as `b29d8b7`. On 2026-11-10, fast-forwarded this branch to
  main at `d2db589`, including E3's tagging adapter/stoppage priors and E4's
  tracking features. No shared contract fields or signatures changed.
- Reproduced Beks's Windows config-path failure using synthetic path semantics:
  `/private/local` was accepted when native Path behaved as PureWindowsPath.
  Replaced host-dependent parsing with explicit PurePosixPath/PureWindowsPath
  checks. The new regression failed before the fix and passes after it, covering
  nested POSIX, Windows-drive, UNC paths, and accepted relative paths.
- Added the E1 method/limitations section to [SETUP.md](../SETUP.md) for E5's
  technical-document assembly. No restricted-data checks ran in this follow-up.

## Next exact action

Have Beks rerun the full suite on Windows with this path fix; request E5's E1
review before merging the follow-up. Run the remaining checks locally using
[SETUP.md](../SETUP.md): full inventory/video verification, baseline regeneration
twice, a real cache round trip, and setup on the other laptops. Keep detailed
reports in ignored directories; record only completion status in this handoff.
E5 can connect the merged E1/E3/E4 modules after E2's decoder is reviewed/merged.
E1 then reviews the pipeline and verifies identical CSV bytes with E5 on a
second laptop. E5 should refresh the stale integrated CONTEXT after integration.

## Blockers and dependencies

- E5's `possession/pipeline.py` is not present on this branch; actual prediction
  exits explicitly with no output until that module is integrated.
- E2's decoder exists on `origin/e2/state-v1`, but is not merged into main at
  `d2db589`. Its current branch handoff supersedes the old E2 handoff on main.
- Azamat's real-data setup run passed after the parser fix. This was reported
  by the user, not independently repeated by the assistant. Video decode count,
  full asset inventory, baseline regeneration, real cache round-trip behavior,
  and full-data runtime measurement remain unverified.
- All-laptop installation, collaborator access and second-laptop reproduction
  are not confirmed. This follow-up ran on macOS arm64 / Python 3.12.12.
  The regression simulates Windows path parsing; a native Windows rerun remains
  required. Beks's handoff reports Windows tests using different NumPy/pandas
  versions from requirements-team.lock; the exact locked Windows setup is open.
- These checks establish input/contract correctness, not measured model accuracy or a
  claimed improvement in spellF1. No model parameters were selected using GT.

## Handoff evidence

- Changed files / behavior: E1 modules, invocation/setup scripts, synthetic
  tests/examples, pinned environment and setup docs listed above.
- Initial implementation: `91b5157`, parser fix: `cfc7fac`, [PR #2](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/2).
  Merged on main as `b29d8b7`. The new path-validation follow-up is on
  `e1/data-contract`, based on `d2db589`, pending review.
- `.venv/bin/python -m unittest discover -s tests -v`: **111 tests passed**
  after refreshing from main, including one new host-independent path regression.
- User-reported `.venv/bin/python scripts/check_setup.py --check-data --data-dir
  ./data`: **passed**, including tactical tracking and available tag input. No
  `--inventory` or `--check-video` flags were supplied; those are not verified.
- `.venv/bin/python scripts/check_setup.py`: contract examples, identical
  full-length synthetic CSV bytes and official submission validation passed.
- `.venv/bin/python -m pip check`: no broken requirements.
- Historical `.venv/bin/python evaluation/run_evaluation.py`: shipped baselines reproduced
  the README's public-window scores; used only as an environment sanity check.
- `.venv/bin/python scripts/predict.py --config configs/input-v1.json --output
  runs/dev/prediction.csv`: expected exit 2 explaining missing E5 integration;
  no prediction written. Unit tests verify invocation using an invented E5 stub.
- `git diff --check`: passed. Verified that `.local/`, `artifacts/`, `runs/` and
  `.venv/` are ignored; supplied evaluator and baseline files were not edited.
- Interface details for consumer review: FeatureData uses `features`/`validity`
  dictionaries; PriorData flags are optional integer arrays; Prediction uses
  `labels`/`diagnostics`. Events remain starter-compatible dictionaries.
- Decision: stdlib raw parsing plus NumPy keeps kloppy/video/GPU optional. The
  CLI fails clearly for absent E5 integration rather than inventing a model.
- Parser-fix decision: ignore numeric raw speed placeholders when both
  coordinates are absent. Keep normal speed validation for observed positions,
  the existing public contracts, and cache invalidation by loader source hash.
- Portability decision: use explicit POSIX and Windows path syntax to enforce
  the existing config policy consistently across laptops; relative paths remain
  allowed. No new configuration keys or dependency changes.
- Help needed: Beks reruns native Windows tests; E5 reviews this follow-up and
  adds the pipeline; E2/E4 complete decoder review; teammates execute remaining
  restricted-data checks locally without sharing extracts.

Update this file with actual local-check results before declaring E1 complete.

