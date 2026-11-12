# Project context

Updated: 2026-11-10. Checked main at `3197721`; E5 additions below are branch
work awaiting review, not merged progress.

## Merged implementation

- Team repository: https://github.com/algaziev7/more-than-a-hack-2027-team.
  The API reports private visibility. Final release requires a public repository.
- PR #1/#4: Almaz's tagging clues and shared PriorData adapter.
- PR #2: Azamat's canonical contracts, loader/cache, deterministic export, CLI
  and synthetic environment/setup checks.
- PR #3: Belek and Isken's validation plan.
- PR #5: Almaz's combined motion/tagging stoppage and restart priors.
- PR #8: Beks's tracking features and official-validator wrapper.
- PR #9: Azamat's cross-platform configuration-path fix and method section.
- Official evaluation code, answer files and supplied baselines are unchanged.
  Main passes 111 synthetic tests in the inspected Python 3.12.12 environment.

Azamat/Almaz previously reported local data loading. Those reports establish
execution only. No private output was read in this E5 session, and no complete
team prediction or accuracy improvement is established here.

## Review branches

E2's decoder (`possession.state_machine.decode`, Decisions 1-11) is merged on
main via PRs #6, #12, #13 and #18; see [E2's handoff](owners/belek_isken.md).
The unresolved live-play/unknown-team behavior needs E2/E3/E4 agreement.

[E5 PR #10](https://github.com/algaziev7/more-than-a-hack-2027-team/pull/10)
(`e5/pipeline-v1`, implementation `6985721`) adds thin loader -> features -> priors -> decoder wiring,
cross-stage checks, local run manifests, synthetic Ubuntu/Windows CI, a PR
template, artifact filename/ignore guards, and team/technical/release docs.
Missing E2 fails before assets are read. Missing/disabled tags remain supported.
No shared signatures, fields or configuration sections changed. Hosted synthetic
CI passed on Ubuntu and Windows for this implementation. See
[Goblin's handoff](owners/goblin.md) for actual test evidence and next steps.
Since then the pipeline also rejects unknown top-level configuration sections and
refuses to export a half that is entirely D.

## Remaining gates

1. Done: E5 and E2 are reviewed and merged. Confirm the combined pipeline on
   synthetic inputs. Hosted CI must require no restricted assets or credentials.
2. An authorised teammate runs the complete system locally and E4 validates
   the exact CSV. A second laptop independently reproduces identical CSV bytes.
3. Owners confirm method/training provenance; finalise the
   [technical draft](TECHNICAL_DOCUMENT.md) and [release package](RELEASE.md).
4. A repository admin configures protection (main is currently unprotected) and
   makes the repository public after the data/history audit. The connected E5
   account has push/triage access, no admin access. No settings were changed.
5. The designated human submitter uploads the frozen team-named file/document
   and records confirmation. Registered team name is not in the checked context.

## Rules and ownership

Output all 199,319 tactical-frame labels: H Barcelona, A Athletic, D stopped
play, X no answer. Ranking uses spellF1. The documented deadline is November 17,
2026; verify updates through registration. Public five-minute labels are pipeline
checks only, never training, tuning, selection or evidence of an accuracy gain.

Hosted AI/CI uses public schemas and synthetic inputs. Restricted assets,
extracts, arrays, predictions and detailed manifests remain local and ignored.
Each laptop sets MTAH_DATA_DIR privately. Follow [TEAM_PLAN.md](../../TEAM_PLAN.md),
[INTERFACES.md](INTERFACES.md), [WORKFLOW.md](WORKFLOW.md) and the owner handoffs.
E1 owns data/export/CLI/contracts, E2 decoding, E3 priors, E4 features/validation,
E5 integration/docs/CI. Azamat reviews E5. Shared files and reviewed commits,
not this conversation, are the team's memory.
