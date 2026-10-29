# E2 algorithm validation and engineering setup

Date: 2026-10-23. Owners: Belek and Isken, working together on E2.
Status: implementation plan; the validation harness and decoder do not exist yet.
E4 reviews algorithm behavior and evaluation policy; E1 owns shared contracts and
environment; E3 supplies stop/restart evidence; E5 owns integration and CI.

Build the validation harness alongside the first decoder. Start with independent
synthetic evidence sequences, verify the official metric semantics, and integrate
with E1/E3/E4 through the proposed contracts. Evaluate predictive quality on
eligible other-match labels if available. Use the competition match for local
pipeline checks and unlabelled diagnostics, within the competition rules.

This plan follows the assignments in [TEAM_PLAN.md](../../TEAM_PLAN.md):
Azamat owns E1, Belek and Isken share E2, Almaz owns E3, Beks owns E4, and
Goblin (AI agents) handles E5 with Azamat reviewing its changes. The E2 task
split below is proposed; both engineers share ownership of the decoder.

## 1. What exists and what is still missing

This assessment used all requested competition documents, the team context,
workflow, interfaces, all five owner files, the dataset README, and the official
scoring/validation and starter source. Match contents were not opened.

| Area | Observed state | Consequence |
|---|---|---|
| Official tooling | Scorer, CSV validator, four reference baselines and public GT exist | Reuse these unchanged |
| Team implementation | No `possession/`, `scripts/`, `tests/`, or `configs/` directories | All team commands below are proposed unless explicitly marked existing |
| Environment | Default `python3` is 3.14.0; numpy, pandas, pytest and Hypothesis are unavailable to it; no project `.venv` | Create an isolated environment; Python 3.11 is available and is a version the repository reports testing |
| Asset location | Expected tactical ATD metadata/raw, homography and Smart Tagging filenames exist in the sibling `dataset/`; `broadcast/` exists | E1 can validate the tracking-based input path locally |
| Video | Expected `tactical/BAR-ATH_tactical.mp4` filename is absent | Resolve only if video is used; this does not block the initial tracking-based decoder |
| Data configuration | `MTAH_DATA_DIR` is unset | Set it before importing `games.py` or invoking a loader |
| Asset integrity | Only presence was checked; no parsing, checksums, completeness or alignment verified | Do not treat the downloaded README or these checks as an integrity certificate |
| Git | Checkout was clean on `main` before this documentation change | The documentation PR uses `e2/validation-plan`; no merged implementation or measured algorithm result is claimed |

[CONTEXT.md](CONTEXT.md) and TEAM_PLAN still describe the bundle root as
unresolved. The presence checks above are newer, but E1 must complete the local
preflight before E5 updates integrated context. No dependency installation,
scorer execution or full-data prediction was performed for this plan.

## 2. Three questions the setup must answer

| Question | Evidence | What passing establishes |
|---|---|---|
| Does the algorithm implement its stated rules? | Hand-designed synthetic scenarios, an independent reference implementation, exhaustive small cases, property tests | Correctness against the agreed model |
| Does it recover football possessions accurately? | Accessible, licensed labels and aligned inputs from other matches, split by match | Quality on that evaluation population, with stated uncertainty |
| Can the team reproduce a valid submission? | Contract checks, local asset preflight, full pipeline, official validator, two-laptop byte comparison | Operational readiness and exact reproducibility |

These questions require separate reports. Synthetic scores do not estimate the
hidden score. Unlabelled possession counts, longer spells or fewer transitions
do not establish improvement. The published full-match baseline, 0.2433 spellF1,
is a competition reference, not a locally measurable target for this match.

The public five-minute GT is for alignment, output and meaning checks only. Do
not use it for parameter search, variant comparison, early stopping or final
candidate selection. Do not create labels or corrections for any part of the
competition match. Automatic tags and algorithmic pseudo-labels are inputs, not
independent validation truth. See [RULES.md](../../RULES.md) and
[FAQ.md](../../FAQ.md).

Restricted assets, frame extracts, derived arrays and detailed local diagnostics
stay on authorised laptops in ignored directories. Hosted AI and hosted CI use
public schemas, source and synthetic cases. A restricted-data failure must be
recreated as a generic synthetic counterexample before sharing it with AI.

## 3. Competitive programming perspective: specify before optimising

Treat E2 as a deterministic sequence algorithm. Write the transition table and
invariants first, then challenge them with small adversarial inputs. A fast
implementation agreeing with a second implementation is useful evidence about
code correctness; it does not prove that either models football correctly.

### Decoder contract and policy decisions

Keep the public API in [INTERFACES.md](INTERFACES.md):

```text
decode(match, features, priors, config) -> Prediction

match:    ordered frames, half IDs, fps
features: H/A evidence [N,2], reliability [N], documented feature masks
priors:   dead evidence/reliability, restart evidence, team hint/reliability
output:   H/A/D/X labels [N], optional diagnostic arrays
```

Use typed synthetic builders against E1's contracts; do not introduce a competing
array schema. If E1's classes are pending, propose a minimal shared fixture first.
Evidence values are bounded heuristics, not calibrated probabilities.

One interface ambiguity needs an explicit E2/E3 agreement: `restart_evidence`
currently has no separate reliability field or stated missing-value convention.
Propose zero support when unavailable for v1, with confirmation from other
credible signals; if that is insufficient, propose a reviewed contract change.
Do not invent an implicit reliability or let a missing tag trigger a restart.

Before implementation, Belek and Isken write down these decisions for E4 review:

| Decision | Proposed initial rule | Required challenge |
|---|---|---|
| Initial state | No confirmed state until credible live-team or dead evidence; output X while unresolved | All-neutral input and a half beginning with a stoppage |
| Live possession | Retain the last confirmed team through a pass, loose ball or unsupported opposing touch | Long pass, aerial duel, repeated deflections |
| Turnover | Confirm credible sustained opponent control; explicit entry/retention hysteresis | Both transient noise and a short real possession |
| Stop/restart | Separate alive/dead transitions from team changes; publish precedence when signals conflict | Strong stop and strong team evidence at the same instant |
| Missing evidence | Reliability zero contributes no support; absence alone cannot create D or a turnover | All ball/player signals missing; neutral or conflicting tags |
| Long uncertainty | Explicit configurable hold/abstain policy with declining confidence | A turnover concealed inside a gap; no claim of recovering unobserved truth |
| Boundary placement | Confirm first, optionally backdate to the start of qualifying evidence | Interrupted candidates, short intervening possessions, half boundaries |
| Equal H/A evidence | Preserve a supported incumbent; otherwise remain unresolved | Team-swap invariance; no default-home bias |
| Half reset | Reset state, confidence, pending candidates and evidence history | Changing the entire first half cannot affect the second half |

Do not set a universal minimum possession duration merely to remove noise. A
short, strongly supported possession must have a path to survive. If the chosen
policy cannot distinguish it from a deflection using its inputs, record that as
an observability limitation and seek an additional general feature.

For every threshold, record its units, comparison (`>` or `>=`), motivation and
source of selection. Express durations in seconds. Proposed persistence rule:
`required_frames = max(1, ceil(seconds * fps))`, with zero-duration behavior
specified separately. Tag timestamp conversion follows the starter's
`round(seconds * fps)` instead; test ties and endpoints. These are different jobs.

Maintain `state`, `candidate_state`, `candidate_start`, `support`, `confidence`
and `confirmed_at` as distinct concepts. A pending transition can be cancelled.
Backdating cannot cross a half boundary or erase an already confirmed stoppage
or intervening possession. Bound the revision window explicitly. Report both
decision delay and final boundary error: offline backdating can improve one
without reducing the other. The submitted algorithm may use the full match.

### Invariants

1. Exactly N output labels in H/A/D/X; X outside published half intervals.
2. Half intervals are independent. For the official match, convert the inclusive
   `half_video_blocks()` endpoints to Python slices by adding one to the end.
3. Missing/invalid evidence cannot silently become positive evidence. In
   particular, NaN positions never become a player or ball at `(0,0)`.
4. Reliability is finite in [0,1]; H/A evidence has the agreed shape, order and
   normalisation. Invalid contracts fail with an actionable error.
5. Inputs and config remain unchanged; repeated calls have no hidden state.
6. Confirmed transitions have a reason and deterministic tie handling. Diagnostics
   enabled versus disabled produce identical labels.
7. A real `H -> D -> H` creates two H possessions. An observation gap is not D.
8. Chunk boundaries, if chunking is later added, cannot become inferred events.
   Exact chunk/full-run equivalence requires transferring state and the complete
   bounded lookahead/revision context; do not require it of arbitrary chunks.

### Independent reference and stress strategy

Belek can build a deliberately simple reference decoder from the written policy
while Isken builds the production decoder, then swap review roles. The reference
may scan candidate windows directly; it should not call production transition,
fusion or boundary helpers. Agreement validates the implementation of that
policy. Separately hand-authored football scenarios challenge the policy itself.

- Exhaustively enumerate evidence symbols `{H, A, stop, restart, neutral}` for
  lengths 0 through 6: 19,531 sequences before configuration variants. Use a few
  fixed representative configs, and compare every label and boundary.
- Include N=0, N=1, no active half, one active frame, all-X output, and multiple
  calls with different lengths. Agree whether empty inputs return empty output
  or a documented error before testing.
- Sweep evidence at `threshold - epsilon`, equality and `threshold + epsilon`;
  duration at `k-1`, `k`, `k+1` frames; candidates interrupted just before
  confirmation; restart at the last frame of a half.
- Use fixed-seed randomized sequences plus shrinking to save a minimal failing
  synthetic case, seed and config. Start with 200 generated cases per PR and a
  larger 5,000-case local sweep before freezing; these are proposed test budgets.
- Re-run each counterexample against both decoders. If both fail a football
  scenario, reconsider the policy instead of accepting agreement as success.

Target O(N) decoding with O(1) rolling transition state plus output/diagnostic
arrays. Use prefix sums or rolling accumulators where they preserve the policy;
avoid repeated full-window scans or repeated long-range rewrites. Benchmark N,
2N and 4N with synthetic evidence, including alternating labels and repeated
near-confirmations. This tests complexity without needing match data.

## 4. The metric adapter must match the actual scorer

Use [possession_metrics.py](../../evaluation/possession_metrics.py) unchanged as
the authoritative metric implementation. A team adapter should call
`pm.evaluate(pm.label_codes(gt), pm.label_codes(pred), bootstrap_n=0)` for
synthetic or eligible external labels. Do not train E2 to match a reimplemented
metric. Pin the upstream code identity in run manifests.

Verified details that affect E2:

- The primary result is `spell_f1_mean`: mean F1 at IoU 0.3, 0.4, 0.5, 0.6, 0.7.
  Only H/A spells count, and matches must have the same team. Matching is greedy
  by descending IoU with deterministic index tie breaks, consuming each spell
  once. Replacing it with optimal bipartite matching changes the metric.
- Graded runs come from non-X **ground truth**, not the prediction. For temporal
  metrics, prediction X is forward-filled within each run and back-filled at
  the run head. An entirely X run remains X; it does not become H or D. Nothing
  fills across separate runs. Frame metrics use the original X values as misses.
- The metric API does not receive `MatchData.half`. Synthetic/external fixtures
  representing separate scored runs need an explicit GT-X gap or separate
  evaluations; merely changing a half ID cannot stop metric-side merging.
- Transition matching defaults to the destination label. Tolerances are 12 and
  25 frames at 25 fps. Final boundary error is `predicted - true`; positive means
  late. Missed and spurious events must accompany latency on matched events.
- `validate_submission.py` counts X as gaps in its descriptive possession count.
  The scorer's filled possession count can differ. Report both with clear names.
- The scorer's sort key is spellF1, macroF1, transition F1 at the looser tolerance,
  then lower mean absolute latency, then name. Source takes precedence over stale
  comments describing macroF1 as the ranking metric.
- The CSV reader/validator tolerates some inputs beyond the documented canonical
  writer format, including extra columns. Our writer should still emit exactly
  `frame,label`, integer 0..N-1, uppercase labels and stable UTF-8/LF bytes.

Create small metric contract tests independent of the decoder:

| Synthetic truth / prediction | Expected property |
|---|---|
| Perfect sequence containing H, A and D | macroF1=1 and spellF1=1 |
| Truth `HHHH`, prediction `HXXH` | One filled H spell, spellF1=1; raw frame misses remain |
| Truth `HHAA`, prediction `HXXA` | Fill gives `HHHA`; X can move a turnover boundary |
| Prediction starts `XXA` in a graded run | Leading X becomes A for temporal metrics only |
| Entire graded run predicted X | No predicted H/A spells; no invented state |
| `HHDHH` against itself | Two H spells separated by D |
| Two graded runs separated by GT X | No spell or fill crosses the gap |
| Same intervals with H/A exchanged in prediction only | Wrong-team spells cannot match |
| Multiple overlapping candidate spells | Exact greedy tie order and one-use matching |
| All-D truth and prediction | No possession objects; spellF1 is 0 by the implementation's convention, not 1 |

Do not require macroF1=1 on a perfect one-class fixture: absent classes contribute
zero in the official three-class average. Likewise, the documentation's empirical
examples about constant guesses or one-frame shifts are not universal identities
for arbitrary synthetic sequences.

## 5. Synthetic scenario suite

Every case declares its purpose, fps, half mask, evidence timeline, latent truth
where meaningful, expected labels/boundaries or allowed outcomes, and config.
Generate evidence independently of decoder helpers. Include both direct E2
evidence fixtures and a smaller set of geometric E1/E4/E3 pipeline fixtures.

| Family | Cases to include | Required observation |
|---|---|---|
| Stable play | H control, A control, passing within a team | No invented possession changes |
| Loose ball | Long pass, aerial duel, rebound without opponent control | Last controlled team persists while support is absent |
| Opponent contact | One-frame touch; several isolated touches; controlled reception | Deflections rejected, supported turnover accepted |
| Short possession | H/A/H with brief but strong A control | No unconditional smoothing-away of A |
| Timing | Gradual evidence rise; abrupt turnover; interrupted confirmation | Measure delay and final boundary error separately |
| Stoppages | H/D/A and H/D/H; sustained stop; a false stop spike | Correct stop/restart ordering and spell separation |
| Live stationary ball | Ball stationary while play remains live | No D from stationarity alone |
| Missingness | Short gap, long gap, missing players, gap straddling a turnover | Defined uncertainty behavior; no missing-equals-dead shortcut |
| Tag limitations | N/A team restart, absent tags, attack/defence semantics | Neutral team hints remain neutral; no raw Team copying |
| Conflicting evidence | Geometry versus tags; simultaneous stop and restart | Deterministic documented precedence |
| Tracking corruption | Identity switch, duplicate slot, implausible jump, NaNs | Reliability/mask handling; no confident switch from a corrupt observation |
| Boundaries | Each half edge, pre-kickoff dead stretch, candidate at half end | Reset all temporal memory and keep outside-half X |
| Endpoints | Final-frame turnover, final-frame stop, incomplete candidate | Explicit flush/cancel behavior without out-of-range writes |
| Invalid inputs | Shape/length mismatch, reversed frame order, bad probabilities, invalid fps/config | Useful error instead of a plausible-looking CSV |

For ideal unambiguous fixtures, require exact expected labels and zero final
boundary error when the policy supports exact backdating. For deliberately noisy
fixtures, predeclare acceptable boundary ranges and allowed uncertainty; do not
move the expected result after seeing the decoder fail. Missing observations can
make the true state unknowable, so some cases test invariants rather than accuracy.

Metamorphic checks complement the examples:

1. Swap all H/A evidence, team mappings, tags and any team-specific config: swap
   H/A outputs and preserve D/X.
2. Reflect synthetic pitch coordinates and all directional context consistently:
   the full pipeline should preserve possession labels. This is an E4/E3
   integration check, not a direct transformation of E2's scalar evidence.
3. Permute player slots within teams and their masks/metadata: team evidence and
   final labels should not depend on slot numbering.
4. Modify the first half arbitrarily: the second-half output stays identical.
5. Change evidence at reliability zero: output is unchanged while inputs remain
   within the valid contract.
6. Duplicate the experiment: labels and exported bytes are identical; diagnostics
   do not change decisions; inputs remain unchanged.
7. Resample synthetic time and adjust fps/durations consistently: compare
   boundaries in seconds with a declared discretisation tolerance. Do not demand
   exact equality across non-equivalent rounding or changed sampling information.

Inserting gaps is a robustness experiment, not an unconditional invariance:
removing the only evidence of a turnover can legitimately change the output.

## 6. Software engineering perspective: an executable, isolated harness

The harness should make the quick, correct path easy: one synthetic test command,
one explicit local prediction command, and one validation/reproduction command.
No decoder imports GT, resolves a data path, downloads data or performs scoring.

Proposed layout, with ownership matching the existing plan:

```text
possession/state_machine.py             E2: pure decoding
configs/state_machine_v1.json           E2: explicit versioned parameters
tests/e2/scenarios.py                   E2: evidence builders and synthetic truth
tests/e2/reference_decoder.py           E2 pair: independent slow reference
tests/e2/test_scenarios.py               E2: semantic behavior and timing
tests/e2/test_properties.py              E2: invariants and metamorphic checks
tests/e2/test_differential.py            E2: exhaustive/random reference comparisons
tests/evaluation/test_metric_contract.py E4, with E2 contributions
tests/contracts/                        E1/E5, all owners contribute
tests/integration/                      E5: synthetic end-to-end pipeline
scripts/validate_e2.py                   E2: synthetic suite/report/benchmark entry
scripts/check_solution.py               E4: official-validator wrapper
scripts/check_data.py                   E1: local preflight
scripts/predict.py                      E1: existing planned CLI contract
requirements-validation.lock            E1: tested exact environment resolution
docs/team/experiments/                  Authors: shareable synthetic/external evidence
runs/                                  Ignored: local run manifests/results/CSV
artifacts/                             Ignored: local caches and debug material
```

All paths above are future work. Agree shared additions with E1/E4/E5 before
implementation; do not edit the official scorer, baselines or existing contracts
silently. No new UI, database, experiment service, GPU or video dependency is
needed for this first version.

### Environment bootstrap

Run from the repository root on each engineer's laptop. These are setup commands,
not a record of execution in this investigation:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt pytest hypothesis
python -m pip check
```

E1 verifies the resolved packages, pins the Python patch version and records exact
versions in the proposed lock file after the first smoke test. Subsequent laptops
install that lock instead of resolving independently. The current unpinned
`requirements.txt` is not an exact environment lock. Keep optional kloppy/video
dependencies separate; do not install the notebook stack just to test E2.

For the current sibling dataset layout, in an authorised local terminal:

```bash
export MTAH_DATA_DIR="$(cd ../dataset && pwd)"
```

Set the variable before Python starts because `games.py` resolves its default
root during import. Do not commit a developer's absolute path.

### Local asset preflight, owned by E1

The proposed checker must validate required assets for the selected feature set,
then write its detailed report to an ignored local directory:

- Tactical source, N=199319, fps=25; every raw ATD record ID equals its ordered
  position plus one. Reject duplicates, missing IDs and reordering even when the
  first/last IDs and record count look correct.
- The existing `check_alignment_raw()` checks count and endpoints; that is not
  sufficient to detect internal duplicate/missing substitutions. The loaded-data
  helper sorts IDs, so it does not establish original row ordering either.
- Team mapping, slot count/schema and masks; metre conversion consistently uses
  the chosen contract's `games.py` pitch (105.3 x 68.0). The metadata's 105 m
  length must not silently mix with it in feature calculations.
- Smart Tagging uses tactical seconds, documented rounding and clipped half-open
  intervals. A phase interval is not an exact restart instant. Unknown teams and
  overlaps remain explicit. Tagging absence is allowed only by an explicit
  no-tags config; malformed supplied tags must not silently disappear.
- Require homography only if the config consumes it; check row alignment and
  validity then. Require video only for a video feature. Broadcast is separate
  and cannot be joined by row number.
- Record input checksums and file sizes locally; key caches by input, schema,
  preprocessing code and relevant config identities. Detect stale cache reuse.

Published half masks are permitted indexing metadata. Published kickoff facts
can motivate generic pre-kickoff tests, but do not implement a frame-specific
label override for this match. Infer D/live transitions through the same policy
used elsewhere.

### Commands and execution lanes

**Existing official commands**, runnable after dependency setup:

```bash
# One-time public-tool smoke check of the shipped baselines only.
python evaluation/run_evaluation.py --gt public --results evaluation/results --out runs/setup/public_smoke --no-detail

# Format check of an existing reference CSV; no match bundle required.
python evaluation/validate_submission.py evaluation/results/baseline_smooth50.csv
```

The first command is a pipeline check, not a candidate leaderboard. It writes
reports under ignored `runs/`. If checking a team candidate against public GT is
needed to diagnose wiring, explicitly record the purpose and use a directory
containing that one candidate. Correct objective wiring defects with synthetic
regressions; do not optimise a public score or repeatedly pick the best variant.

**Proposed commands, unavailable until the files above are implemented:**

```bash
# PR lane: synthetic inputs only.
python -m pytest tests/e2 tests/evaluation tests/contracts tests/integration -q
python scripts/validate_e2.py --suite synthetic --seed 0 --out runs/e2/synthetic

# Release engineering lane: synthetic performance/stress tests.
python scripts/validate_e2.py --suite stress --seed 0 --out runs/e2/stress

# Authorised local terminal: restricted inputs and outputs stay local.
python scripts/check_data.py --config configs/state_machine_v1.json --out runs/setup/preflight.json
python scripts/predict.py --config configs/state_machine_v1.json --output runs/e2/candidate/team_name.csv
python scripts/check_solution.py runs/e2/candidate/team_name.csv
```

The config filename is provisional; E1/E5 may compose it into a complete pipeline
config. The checker must propagate the official validator's nonzero exit status.
After prediction exists, the existing official command can directly validate the
exact generated file:

```bash
python evaluation/validate_submission.py runs/e2/candidate/team_name.csv
```

Hosted CI executes the synthetic lane from a fresh checkout with no competition
assets and no GT-dependent candidate scoring. An integration test blocks reads
from `evaluation/gt/` while predicting synthetic inputs. Static import checks
are supplementary; a clean run with GT unavailable proves the execution path.
PR failures should print only synthetic counterexamples.

## 7. Measuring algorithm behavior

The synthetic/external report includes the same metric implementation, plus
diagnostics that help explain an E2 failure:

| Output | Why it matters |
|---|---|
| spellF1 mean and per-IoU precision/recall | Distinguishes loose recovery from accurate boundaries |
| macroF1 and per-class H/A/D precision/recall | Exposes false stops and team confusion |
| Transition precision/recall at 12 and 25 frames | Separates flicker, missed events and lag |
| Signed, absolute and p90 boundary error; matched/missed/spurious counts | A low error on very few matched events is not success |
| Confirmation delay versus emitted boundary | Makes the cost and effect of backdating visible |
| Short-possession recovery and split/merge failures | Protects against solving flicker by erasing true possessions |
| Raw and filled X behavior | Exposes state carry across concealed transitions |
| Runtime and peak memory by stage | Prevents scorer or loader time being attributed to E2 |

Measure boundary timing against generator transition IDs in synthetic scenarios,
and use official matching for official metric reports. Report turnover, stop and
restart timing separately. For eligible external labels, stratify by half,
duration and input missingness without repeatedly selecting on every subgroup.

For unlabelled competition runs, report only engineering/behavioral diagnostics:
input coverage, invalid-value counts, X share, predicted duration distribution,
transition reasons, module disagreement, runtime and checksums. These cannot
produce precision, recall or boundary accuracy. Detailed arrays and plots remain
local. Do not use a plausible target possession count as a tuning objective.

The official spell overlap implementation loops over GT and predicted spells.
Keep synthetic scorer cases reasonably small; benchmark full-length E2 decoding
separately so an adversarial highly fragmented metric calculation does not mask
decoder complexity.

## 8. Other-match validation and candidate selection

E4 owns a four-hour initial feasibility search, as already proposed in TEAM_PLAN.
This investigation did not verify or select an external dataset. A candidate
source must provide both usable inputs and labels compatible with this task:

1. Another match, with documented licence, provenance and organiser access.
2. Frame-aligned team possession and dead/live status, or a documented defensible
   mapping with known uncertainty. Sparse event timestamps alone are not dense
   ground truth for controlled possession and restarts.
3. An explicit adapter for frame rate, team IDs, coordinate units, half boundaries
   and possession definition. Validate alignment independently of E2 output.
4. A record of human labelling, if any: who, protocol, amount, ambiguity policy
   and a second review of an agreed sample from those other matches.

Split by match before tuning: development matches for parameters and a reserved
test set for a frozen candidate. Never randomly split adjacent frames. If labels
only cover clips, keep the whole source match in one split and preserve gaps as
ungraded; do not splice unrelated clips into a continuous possession timeline.
One external match supports only limited evidence, not a strong generalisation
claim. If repeated iteration consumes the reserved set, obtain a new one or
state that it has become development data.

Freeze an ablation list before comparison: first deterministic decoder, then
hysteresis, reliability gating, stop/restart fusion, bounded backdating, and the
chosen long-gap policy. Change one component at a time, include the agreed
reference method, record every candidate and retain regressions. Tune on
development data; use the reserved set for the final comparison, without tuning
back to it. External scores are not directly comparable with the published
BAR-ATH score unless evaluated on the same underlying data, which is unavailable.

Compute metrics separately per match and report the predeclared aggregation
(proposed: mean per-match spellF1, plus individual-match results). At other frame
rates, the official metric's duration reporting assumes 25 fps and its default
transition tolerances are frame counts. E4's external adapter must use a verified
25-fps evaluation axis or explicitly report external-rate diagnostics with scaled
tolerances; do not silently reinterpret seconds or modify official code.

For uncertainty, use paired candidate differences on the same resampled whole
matches when enough matches exist. If using temporal blocks within matches,
preserve boundaries and explain the limited independence assumption. Do not
bootstrap individual frames, treat overlapping confidence intervals as a test,
or adopt the repository's empirical ~0.04 band as a universal significance rule.
The official per-candidate bootstrap does not by itself provide a paired
candidate comparison.

If no eligible labels are available, stop the search at its timebox. Choose the
simplest candidate that meets the agreed semantics, synthetic robustness,
resource and reproducibility gates, using documented reasoning. State:
**"Correctness and reproducibility verified; improvement on the hidden match
has not been measured."** No substitute labels from the competition match.
Use that wording only after the corresponding correctness and reproduction
gates have passed; until then report those checks as pending.

## 9. Reproduction, reports and failure handling

Each proposed run manifest records:

```text
run_id, purpose (synthetic | external_dev | external_test | public_smoke | unlabelled_local)
code_commit, dirty_tree_status, upstream_metric_identity, schema_version
config_content_hash, input_hashes_or_synthetic_seed, evidence_provenance
python_version, dependency_lock_hash, platform, thread_settings
command, thresholds_selection_basis, started_at, stage_runtimes, peak_memory
output_sha256, validation_exit_status, checks_run, checks_passed
metrics_if_eligible, limitations, decision
```

Use a clean frozen commit for release; a dirty development run needs its patch
identity recorded locally. Store private manifests and diagnostic files under
`runs/`, not in owner handoffs. Public experiment notes can reference synthetic
fixtures or permitted external evidence, with no restricted extracts or paths.

Write outputs atomically, keep prior runs immutable, and fail on an invalid
contract instead of filling or truncating to 199319 rows. Explicitly test a
missing asset, unwritable destination, corrupt config and stale cache. Verify
that no-tags mode is intentional and still generates a valid output.

For release, both of you use the same frozen commit, resolved config, dependency
lock and authorised input hashes on separate laptops. Regenerate from inputs
(including a cold-cache run), validate the exact CSV, and compare SHA-256 hashes.
Also compare diagnostic-on/off and warm/cold-cache output hashes. Seed all
randomness, sort unordered inputs, specify numeric comparisons and CSV newlines;
a seed alone does not guarantee cross-machine byte equality.

E5 collects the reproduction evidence and checks tracked files/history before
publication. The final three deliverables remain the team-named CSV, public
regeneration repository and short technical document. Submission instructions
and the documented deadline are in [SUBMISSION.md](../../SUBMISSION.md); the
team should verify organiser updates through its registration channel.

## 10. Work split, sequence and acceptance gates

The hour ranges below are estimates of elapsed focused pair sessions, with both
of you working concurrently. Budget roughly 12–16 hours each for the initial
decoder-plus-harness increment, then use the existing team milestones for
integration and finalisation. Availability and the E2 task split still
need agreement; this is not an extra 32-hour commitment per person.

| Session | Isken | Belek | Shared exit condition |
|---|---|---|---|
| 0–2 h | Draft transition table, thresholds policy and invariants | Define scenario format and metric examples | E1/E3/E4 contracts understood; ambiguous policies written down |
| 2–5 h | Implement smallest deterministic decoder | Build scenario runner, reference decoder and hand-authored cases | Stable possession, turnover, stop/restart, X and half reset work |
| 5–8 h | Add candidate cancellation, reliability and bounded backdating | Differential sweeps, property tests and shrinking | No failures in agreed critical cases; minimized regressions saved |
| 8–12 h | Integrate E4 features and E3 priors with E5 | Report generation, full-length synthetic benchmark and no-GT checks | Synthetic end-to-end CSV validates; documented local command ready |
| 12–16 h | Review reference/tests and resolve policy failures | Review decoder; run the same setup on the second laptop | Both understand both halves; E4 review ready; local run/reproduction when E1 preflight passes |

E4's external-data feasibility work can proceed concurrently. E1/E3/E4 delays
must not block E2's synthetic lane. Request their smallest conforming fixtures
instead of taking over their modules.

Acceptance gates:

- **G0 — specification:** interfaces and transition policy agreed; every
  parameter has units and a permitted selection source; no public-GT dependency.
- **G1 — correctness:** metric contract tests, semantic scenarios, threshold
  edges, reference comparisons and invariants pass. No unresolved critical
  counterexample is hidden by a better average score.
- **G2 — integration:** complete synthetic pipeline produces canonical CSV;
  official validator accepts it; invalid inputs fail; no-tags behavior and
  half independence pass; the decoder cannot read GT.
- **G3 — operational:** local preflight passes for assets actually used; full
  tracking-based run completes; exact output validates. Record runtime and
  memory, including a synthetic N/2N/4N scaling check. Set a laptop-specific
  runtime budget before evaluating candidate speed; no performance is claimed yet.
- **G4 — evidence:** either a frozen external evaluation with provenance and
  limitations, or an explicit statement that hidden-match improvement is
  unverified. Public-window score is never a selection gate.
- **G5 — release:** two independent regenerations have identical CSV hashes;
  final file validates; repository and technical document reproduce that file.

The first deliverable should be the smallest runnable synthetic vertical slice:
**one typed input fixture -> E2 decoder -> labels -> official metric check and
CSV validation**, with pass, turnover, stoppage and half-reset scenarios. Build
that before optional models, video features or a parameter-search dashboard.

## Source map

- Task and label semantics: [README](../../README.md),
  [CHALLENGE](../../CHALLENGE.md), [OVERVIEW](../../OVERVIEW.md).
- Permitted validation and handling: [RULES](../../RULES.md),
  [FAQ](../../FAQ.md), [WORKFLOW](WORKFLOW.md).
- Frames/assets: [DATA](../../DATA.md), [games.py](../../games.py),
  [ATD loader](../../starter/load_atd.py),
  [tagging loader](../../starter/load_smart_tagging.py). The separately supplied
  `dataset/README.md` repeats the starter layout; it is not an asset manifest.
- Metric and submission authority: [EVALUATION](../../EVALUATION.md),
  [metric code](../../evaluation/possession_metrics.py),
  [scorer](../../evaluation/run_evaluation.py),
  [validator](../../evaluation/validate_submission.py),
  [SUBMISSION](../../SUBMISSION.md).
- Team ownership: [TEAM_PLAN](../../TEAM_PLAN.md), [CONTEXT](CONTEXT.md),
  [INTERFACES](INTERFACES.md), [E2 handoff](owners/belek_isken.md),
  [E1](owners/azamat.md), [E3](owners/almaz.md), [E4](owners/beks.md), [E5](owners/goblin.md).
