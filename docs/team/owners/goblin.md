# Goblin (AI agents) — Integration and documentation

- Owner: Goblin (AI agents)
- Status: first integration increment implemented; PR #10 awaiting E1 review
- Branch: `e5/pipeline-v1`, based on main `3197721`
- Reviewer: E1 (Azamat)
- Owned files: pipeline; integration tests; run-manifest/report assembly; CI;
  .gitignore; team/technical/release docs
- Last update: 2026-11-10
- Reference: implementation commit `6985721`;
  [PR #10](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/10)

## Completed

- Inspected fetched main and owner branches. E1/E3/E4 are merged; E2's decoder
  at `9883b4d` remains in PR #6. No existing E5 implementation was found.
- Created an isolated E5 worktree without switching or modifying the shared
  E1 checkout. Used public code and invented inputs only; no restricted-data job.
- Wired E1 loading -> E4 features -> E3 combined priors -> E2 decode through
  `predict_match(data_dir, config)`. Missing E2 errors before opening inputs.
  Cross-stage contract/length checks reject incompatible timelines and invalid
  predictions; excluded frames must be X. No label repair or placeholder model.
- Exercised missing/disabled tags through the real synthetic ATD loader and
  E4/E3. Preserve E2's diagnostic reasons and add a local `run_manifest` record.
- Added code/config/input identities, environment, seed and runtime capture;
  `write_run_manifest` verifies exact exported bytes and official full-length
  validation before recording output checksum/checks. Records remain local.
- Added asset-free Ubuntu/Windows CI, a PR template, numeric/bundle ignore
  patterns and filename-only tracked-artifact guards. Supplied evaluation,
  baselines, starter files and other owners' implementation files are unchanged.
- Refreshed integrated context and assembled TEAM_README, a technical draft,
  experiment template and explicit release/reproduction gates.
- Repository API audit: private repo, main unprotected, connected account has
  push/triage but no admin access. No visibility/access/protection changes made.

## Verification

Initial main baseline: `python -m unittest discover -s tests` — 111 pass on
Python 3.12.12/macOS arm64 with the existing `requirements-team.lock` environment.

- E5 suite: `python -m unittest discover -s tests` — 127 discovered, 125 pass,
  2 explicit real-decoder skips because E2 is absent from main.
- Disposable E2 `9883b4d` overlay: same command, all 174 pass, no skips. Includes
  a full-length invented pipeline CSV, official validation and manifest check.
  The exact overlay recipe is in the [checkpoint report](../experiments/2026-11-10-e5-integration.md).
- `python scripts/check_setup.py`: synthetic contracts, deterministic full-length
  export and official validation pass. `python -m pip check`: no broken requirements.
- `python -m tabnanny possession scripts tests .github`, `git diff --check`,
  repository filename guard and documentation links/example syntax pass.

- Hosted synthetic CI passed on Ubuntu and Windows for `6985721`, on both
  push and PR events. [PR CI run](https://github.com/algaziev7/more-than-a-hack-2027-team/actions/runs/42823964683).
  No assets or credentials were needed by those checks.

All inputs invented; no public answer labels or competition assets read.

## Review, blockers and next exact action

- E1 reviews this PR's wiring, diagnostic manifest metadata, reproducibility
  helper and docs. No shared contract/signature/config-section changes.
- E2/E3/E4 review the combined wiring and synthetic evidence; E2's internals
  were not copied into this branch. Real-decoder tests skip explicitly until
  E2 is integrated; the disposable overlay is separate compatibility evidence.
- A maintainer must configure branch protection and final public visibility;
  this account cannot administer those settings. Hosted synthetic CI passed.
- Complete local full-data execution, official validation and independent
  second-laptop CSV-hash comparison after E2/E5 review/merge. Synthetic bytes
  and same-laptop checks do not satisfy the independent reproduction gate.
- Collect owners' final method/provenance sign-offs and registered team name,
  then assemble the final team-named CSV/Markdown and human upload confirmation.
- Full-match accuracy, improved spellF1, a final selected submission and full-data
  execution across laptops are unverified. Use allowed evidence only.

Next: Azamat reviews PR #10 and E4 reviews E2 PR #6. Integrate reviewed E2/E5,
then have an authorised teammate execute the [local release procedure](../RELEASE.md).
The branch is committed/pushed; the shared E1 checkout remains unchanged.
Branch work is not integrated until merged.
