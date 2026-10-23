# Five-engineer delivery plan

## Objective and assumptions

Build a reproducible program that reads the provided match assets and writes
199,319 rows of `frame,label` for the tactical video. Labels are H (Barcelona),
A (Athletic Club), D (out of play), or X (abstain). Recover complete possession
periods, including their boundaries. Official ranking uses spellF1; macroF1 is
the first tie-break. The published full-match baseline is 0.2433 spellF1.

All five engineers are equally experienced and use AI tools on separate laptops.
The team reports having the bundle. Its location and completeness have not been
verified: this checkout has no configured assets, and the downloaded README
only documents the expected layout. Engineer 1 resolves the local setup first.

Use one team-owned repository containing this starter and the team solution.
Give each engineer a separate clone and task branch. Preserve upstream history
and attribution. The final code repository must be public. No match assets or
reconstructable derived data belong in it, even during private development.

The following files, modules, commands, and estimates are planned work; they are
not an implemented solution. Sources: README.md, CHALLENGE.md, DATA.md,
EVALUATION.md, RULES.md, SUBMISSION.md, FAQ.md, and the starter loaders.

## Ownership and equal workload

Exactly one person owns each role. Engineer 4 is Engineer 2's scheduled review
partner; do not allocate a sixth person to the core logic. Everyone writes tests
and their technical-document section. Engineer 5 assembles those sections.

Initial budget: **32 focused hours per person**, or 160 team hours. This is a
planning estimate, not a promise. At four focused hours/day it is eight working
days; scale the calendar to actual availability. Each person's budget includes
20 hours implementation, 6 hours tests/verification, 4 hours review/integration,
and 2 hours documentation/handoffs. Rebalance after the first integration.

| Owner | Owns                             | Main deliverable                                              | Reviewer |
|-------|----------------------------------|---------------------------------------------------------------|----------|
| E1    | Data and infrastructure          | Canonical input, environment, runnable CLI and exporter       | E5       |
| E2    | Possession state machine         | Stable H/A/D sequence with accurate transitions               | E4       |
| E3    | Dead ball and Smart Tagging      | Stop/restart evidence and team hints                          | E2       |
| E4    | Tracking features and evaluation | Reliable geometric evidence and validation policy             | E3       |
| E5    | Integration and documentation    | Connected pipeline, reproducibility audit, submission package | E1       |

These are primary ownership boundaries, not silos. Reviewers examine substantive
behavior. Nobody silently changes another module's contract. If a role is ahead,
its owner takes a reviewed helper task from the busiest role.

## E1 — Data and infrastructure

Own `possession/contracts.py`, `possession/data.py`, `possession/export.py`,
`scripts/predict.py`, dependency lock files, and setup instructions.

1. Confirm each member has authorised access; registration is already done if
   everyone has it. Locate the extracted bundle on each laptop and set
   `MTAH_DATA_DIR` to the directory containing `tactical/` and `broadcast/`.
2. Inventory required filenames, sizes, and local checksums without committing
   assets. Confirm tactical frame count, exact ordered tracking IDs, team mapping,
   and units. Validate every ID, not only the first and last or the record count.
3. Create a common Python environment and pin exact versions after verifying
   installation. Keep core execution lightweight and video dependencies optional.
4. Run the shipped scorer and baseline locally. Check that baseline regeneration
   is repeatable; preserve the shipped reference CSVs and record version changes.
5. Implement canonical arrays and typed contracts from INTERFACES.md. Supply
   synthetic fixtures immediately so the other four owners can work in parallel.
6. Cache local processed inputs by asset/config/schema hashes. Preserve observed
   versus estimated values and validity masks; do not silently fill all gaps.
7. Implement the CLI and deterministic CSV writer. The CLI calls E5's pipeline;
   E1 owns invocation, configuration loading, paths, seeds, and output formatting.

Acceptance: all five laptops pass setup checks; identical inputs/config/code
produce identical CSV bytes; an unset/mistyped data path gives a useful error;
frame IDs, units, and missing values have synthetic tests. Supply a smoke test
that does not need restricted data. Do not require a GPU for the first version.

After setup: own cache invalidation, reproducibility, installation failures, and
performance bottlenecks. This keeps the workload balanced after the first day.

## E2 — Possession state machine

Own `possession/state_machine.py`, state-machine configuration, and its tests.

1. Implement H, A, and D states using E4's tracking evidence and E3's priors.
   Keep confidence and pending-transition evidence separate from the final label.
2. Maintain possession during passes, loose balls, short occlusions, and brief
   opponent touches. Require sustained credible control evidence for a turnover.
3. Implement hysteresis: entering a new state requires stronger evidence than
   remaining in the current one. Make thresholds explicit and motivated.
4. Treat alive/dead changes separately from team changes. A restart starts a new
   possession even when the same team had the previous possession.
5. Avoid carrying state across halftime. Reset at each supplied half boundary;
   do not assume the first graded frame of every half is a live kickoff.
6. Handle missing evidence deliberately. Missing ball does not imply D. Avoid
   inventing confident team changes when both team signals are weak.
7. Address confirmation delay: when a transition is confirmed, an offline pass
   may place its boundary at the start of the supporting evidence. Test this
   carefully so it does not absorb a brief deflection or erase a short possession.
8. Return labels plus local diagnostic reasons. Document how X is used; the
   scorer fills X for spellF1, so abstention can carry a wrong state over a change.

Acceptance: synthetic sequences cover a pass, deflection, controlled turnover,
short true possession, stoppage, same-team restart, missing ball, noisy tracking,
and half reset. Measure boundary error on synthetic cases. Longer smoothing alone
is not evidence of improvement. E4 reviews transition behavior and edge cases.

Start with a deterministic state machine. An HMM or duration model is optional
after integration and only if legal validation supports the extra complexity.
The competition processes a complete match; live collaboration does not require
the prediction algorithm to run causally or in real time.

## E3 — Dead ball and Smart Tagging

Own `possession/tagging.py`, `possession/dead_ball.py`, their configuration/tests.

1. Reuse the starter XML loader. Convert tag times onto the tactical frame axis
   and preserve overlapping tags, missing teams, and tag types.
2. Build soft live/dead and restart evidence using SET PIECES, geometric features,
   player/ball motion, and their persistence. A tag interval is not a precise
   dead-ball interval and a restart tag is not necessarily the restart instant.
3. Handle throw-in Team=N/A explicitly: keep useful restart evidence, but do not
   fabricate the restarting team. Infer a team only from additional evidence.
4. Define code-specific team semantics. An attacking phase names the attacking
   side; a defending phase names the defending side. Do not copy every Team tag
   directly into possession. Keep ambiguous phases neutral.
5. Do not treat a stationary ball, missing ball, or a bad tracking position as a
   sufficient stoppage detector. Several weak clues may support an inference.
6. Output separate dead-ball, restart, and team-hint strengths with reliability
   masks. Keep weak/missing signals neutral. Document correlations: tactical
   tags come from the same video/tracking and are not independent ground truth.

Acceptance: synthetic cases cover each restart type, N/A and unknown teams,
overlapping/conflicting tags, rounding/clipping at frame boundaries, missing
tags, and a live stationary ball. The pipeline still runs when tagging is disabled.

Optional after integration: a local tactical-video signal for unresolved
stoppages. Timebox this; E1 owns any added dependency and E4 owns its evaluation.
Broadcast alignment and replacement tracking are stretch work, not first-release
dependencies. A homography projects ground-plane positions; airborne ball
projections can be misleading.

## E4 — Tracking features and evaluation

Own `possession/features.py`, `scripts/check_solution.py`, feature tests, and
evaluation policy. Reuse official scoring/validation code without modifying it.

1. Calculate ball-to-team distances in metres, nearest and next-nearest distances,
   distance advantage, ball speed, and short-window control evidence.
2. Add motion consistency, local player density, ball boundary proximity, and
   missing-data duration where they help distinguish control or stoppages.
3. Preserve reliability. Track slots are not player identities: avoid assuming
   a slot's velocity is valid across an identity switch. Reject implausible jumps
   algorithmically. Never convert NaN to a real location such as (0,0).
4. Supply raw features and a simple interpretable H/A evidence pair conditional
   on play being live. E2 owns temporal persistence; E4 does not add competing
   possession smoothing. E3 consumes motion features for dead-ball inference.
5. Establish legal validation before experiments. Public five-minute labels are
   pipeline checks only. No choosing thresholds, variants, or final output from
   their score. Bootstrap on that window does not make model selection legal.
6. Build synthetic scenarios and metamorphic checks: swap team identities and
   expect swapped H/A; mirror pitch coordinates and preserve possession; insert
   controlled observation gaps; verify no state carries over a half boundary.
7. Timebox discovery of usable, licensed labelled data from other matches to
   four hours initially. Require organiser access and documented provenance. If
   available, split by match, tune on development matches, and compare frozen
   candidates on held-out matches. Use paired bootstrap on appropriate temporal
   units; never treat neighbouring frames as independent samples.
8. If no suitable external labels are available, use synthetic regression tests,
   engineering arguments, and permitted unlabelled diagnostics. Explicitly report
   that full-match performance improvement is unverified. A plausible possession
   count or lower transition count does not prove higher spellF1.

Acceptance: feature units/shapes/masks are tested; every run records its purpose
and evidence source; the exact final file passes the official validator; no code
path for prediction reads public GT. E5 owns report assembly to limit this role's
load. Every owner supplies their own tests and runs their own experiments.

## E5 — Integration and documentation

Own `possession/pipeline.py`, integration tests, CI configuration, `.gitignore`,
team README, experiment manifests/report assembly, and technical-document assembly.

1. Set up the team repository, branch protection where available, and a small PR
   template covering interface changes, test evidence, and context updates.
2. Build a thin pipeline against synthetic contracts immediately. Keep all
   modules callable independently and provide a basic fallback for missing tags.
3. Wire E1 inputs -> E4 features -> E3 priors -> E2 decoding -> E1 export.
   E5 decides wiring and execution order; each module owner decides its internals.
4. Add CI for synthetic tests, contract checks, and formatting. Restricted data
   and credentials must not be needed by hosted CI. Match runs stay local.
5. Maintain the shared context at integration checkpoints. Assemble a run manifest
   with code commit, config hash, input hashes, dependency versions, seed, runtime,
   output checksum, and checks performed. Keep private artifacts local.
6. Collect technical sections from E1–E4 continuously: method, assets, possession
   rules, training-data provenance, limitations, and reproduction instructions.
7. Independently reproduce the selected submission on a second laptop from a
   clean checkout. Resolve differences with E1; compare exact CSV hashes.
8. Prepare the final team-named CSV, public code URL, and short PDF/Markdown
   document. A human submitter uploads the exact validated file and records the
   submission confirmation. Do not rely on the final day for the first upload.

Acceptance: all module fallbacks work; synthetic CI passes; fresh-machine output
matches; data and generated files are absent from Git; docs describe the actual
implementation. Rotate meeting facilitation/release assistance, but keep one
integration owner during each milestone to avoid conflicting merges.

## Sequence and checkpoints

Hours below are cumulative focused hours **per engineer**, worked concurrently.

| Checkpoint | E1 | E2 | E3 | E4 | E5 |
|---|---|---|---|---|---|
| 0–4 h | Locate assets; lock contracts; synthetic inputs | State design and synthetic sequences | Tag semantics and synthetic XML | Feature definitions and validation rules | Team repo, thin pipeline, docs skeleton |
| 4–12 h | Canonical loader, setup checks on every laptop | Basic hysteresis and resets | Tag rasterisation, initial stop/restart evidence | Distances, speeds, masks, synthetic tests | Connect modules; first valid complete CSV |
| 12–20 h | Cache/reproducibility fixes | Controlled turnovers, gaps, boundary timing | Conflicts, N/A, false stoppages | Robust features; legal external evaluation if feasible | Integration regressions and local manifests |
| 20–26 h | Portability/runtime and review | Failure cases and review | Failure cases and review | Frozen-candidate checks, external comparisons if available | Candidate integration and technical draft |
| 26–32 h | Reproduction with E5 | Freeze logic; write method section | Freeze priors; document limitations | Validate final file and evidence claims | Second-laptop reproduction, release package |

**First gate, hour 4:** contracts and synthetic examples agreed. If E1 has data
setup trouble, others continue against fixtures; nobody waits idle.

**Second gate, hour 12:** all five modules connect and a valid full-length CSV is
generated locally. Quality can be basic. Fix integration before optional research.

**Third gate, hour 26:** choose a candidate using allowed evidence; freeze config
and dependencies. A public-window score increase is not a selection criterion.

**Release gate, hour 32:** exact reproducibility on another laptop, official
validation, completed technical document, and no restricted files in Git.

The repository lists November 17, 2026 as the submission deadline. Treat that as
the documented date and verify any organiser updates through registration email.
Aim to have an uploadable package at least 48 hours before the official deadline.
If time is short, cut video processing, broadcast alignment, new tracking, and
complex models before cutting integration, validation, or reproducibility.

## First joint session

1. Assign E1–E5 names in owner files; confirm actual available hours.
2. E5 creates the team repo from this starter; everyone clones it separately.
3. E1 gets the real bundle root from each member and gives setup commands.
4. Spend 30–45 minutes agreeing on INTERFACES.md. E1 implements the contracts.
5. Everyone starts a separate branch and a small vertical task with synthetic
   tests. E5 connects stubs while E1 checks local data.
6. At session end, each owner updates their handoff and pushes their branch;
   reviewed work is merged. E5 updates CONTEXT.md with the integrated state.

Existing commands (run locally after installing dependencies):

```bash
python -m pip install -r requirements.txt
python evaluation/run_evaluation.py
# Set this to the actual root that contains tactical/ and broadcast/:
export MTAH_DATA_DIR='/absolute/path/to/extracted/bundle'
python starter/baseline.py
python evaluation/validate_submission.py evaluation/results/baseline_smooth50.csv
```

The baseline script also scores its outputs on the public window. That is a
setup check, not permission to select or tune variants using that score.

Planned team command, to be implemented by E1/E5:

```bash
python scripts/predict.py --config configs/final.json --output runs/final/team_name.csv
python evaluation/validate_submission.py runs/final/team_name.csv
```

## Risks that change implementation

- The ball is absent on about 41% of graded frames: missingness is a first-class
  input, not a dead-ball label.
- ATD frames are 1-based; submission frames are 0-based. Use `frame_id - 1`, not
  the corrected-tracking offsets in games.py.
- Team tags can describe defending teams; N/A is not a team. Raw tag copying
  produces systematic possession errors.
- The second half's graded interval includes time before kickoff. Resetting to
  a live state at its first frame would be incorrect.
- Excessive persistence merges real short possessions; insufficient persistence
  invents turnovers. Test both failure modes and boundary delay.
- The competition's hidden full-match score cannot be measured locally. Do not
  promise improvement from the tiny public example or synthetic tests alone.
- Restricted assets cannot be sent to hosted LLMs per FAQ.md. Use AI for code,
  public documentation, and synthetic cases; execute data jobs locally without
  exposing restricted contents in chat, tool output, or committed handoffs.
