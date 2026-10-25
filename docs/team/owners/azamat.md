# Azamat — Data and infrastructure

- Owner: Azamat
- Status: E1 infrastructure implemented and synthetically verified; awaiting consumer review and local bundle checks
- Branch: e1/data-contract
- Reviewer: E5
- Owned files: possession/contracts.py; possession/data.py; possession/export.py; scripts/predict.py; environment files
- Current milestone: contracts/fixtures delivered; loader, cache, export and invocation ready for integration
- Last update: 2026-10-25

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

## Next exact action

Rerun `scripts/check_setup.py --check-data --data-dir ./data` locally after
the missing-position/speed fix. A successful full-data run is not yet confirmed.
Have E2/E3/E4/E5 review the concrete constructor fields and consume the shared
fixtures. Run the local commands in SETUP.md on each laptop: bundle validation,
optional video/inventory checks, and baseline regeneration into ignored runs/.
E5 can now wire its pipeline; E1 will review it and verify byte-for-byte export.

## Blockers and dependencies

- E5's `possession/pipeline.py` is not present on this branch; actual prediction
  exits explicitly with no output until that module is integrated.
- The user ran the real-data check locally and reported the parser error
  `missing ATD position must not carry speed`. The fix was reproduced and
  verified with invented inputs only; no restricted tracking rows were exposed
  to the assistant. Full-data compatibility after the fix, video decode count,
  baseline regeneration, and full-data runtime remain unverified.
- All-laptop installation, collaborator access and second-laptop reproduction
  are not confirmed. Only macOS arm64 / Python 3.12.12 was exercised.
- These are synthetic correctness results, not measured model accuracy or a
  claimed improvement in spellF1. No model parameters were selected using GT.

## Handoff evidence

- Changed files / behavior: E1 modules, invocation/setup scripts, synthetic
  tests/examples, pinned environment and setup docs listed above.
- Initial implementation: `91b5157`, [draft PR #2](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/2).
  The parser fix and this handoff travel together on `e1/data-contract`.
  Branch progress is not yet accepted on main.
- `.venv/bin/python -m unittest discover -s tests -v`: **38 tests passed**.
- `.venv/bin/python scripts/check_setup.py`: contract examples, identical
  full-length synthetic CSV bytes and official submission validation passed.
- `.venv/bin/python -m pip check`: no broken requirements.
- `.venv/bin/python evaluation/run_evaluation.py`: shipped baselines reproduced
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
- Help needed: E2/E3/E4 review contracts; E5 consumes contracts and adds pipeline;
  human teammates execute restricted-data checks locally without sharing extracts.

Update this file with actual local-check results before declaring E1 complete.

