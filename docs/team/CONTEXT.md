# Project context

Updated: 2026-11-14. Checked `main` at `5e8619b` after fast-forwarding from
`origin/main`. The implementation statements below describe merged code;
dated experiment records and older owner-handoff sections remain historical.

## Merged implementation

- Team repository: https://github.com/algaziev7/more-than-a-hack-2027-team.
  The last recorded API inspection (2026-11-10) reported private visibility.
  Final release requires a public repository.
- PR #1/#4: Almaz's tagging clues and shared PriorData adapter.
- PR #2/#9: Azamat's contracts, loader/cache, deterministic export, CLI,
  synthetic setup checks, and cross-platform configuration-path fix.
- PR #3: Belek and Isken's validation plan.
- PR #5/#11: Almaz's combined motion/tagging stoppage and restart priors,
  bounded missing-observation handling, and aggregate diagnostics.
- PR #8/#14: Beks's tracking features, validator wrapper, and revised evidence
  reliability.
- PR #10: Goblin's pipeline wiring, synthetic CI, private run manifests, and
  release/documentation scaffolding.
- PR #6/#12: Belek and Isken's decoder plus reviewed edge-case fixes.
- PR #13: tracking-first fusion, one-second controlled-possession dwell,
  bounded boundary backdating, tag protection, and restart look-ahead.
- PR #18: period-start metadata plus the second-half start gate and start-tag
  eligibility rule (Decisions 10-11).
- Official evaluation code, answer files, and supplied baselines are unchanged.
  This documentation refresh reproduced all 236 synthetic tests on Python
  3.12.12 with the pinned dependencies; the asset-free setup smoke and official
  format validation also passed without reading match assets.

Azamat/Almaz previously reported local data loading. Those reports establish
execution only. No private output was read in this documentation session, and
no complete team prediction or accuracy improvement is established here.

## Integrated behavior

`possession.pipeline.predict_match` runs loader -> tracking features -> combined
priors -> decoder and enforces shared types, timeline alignment, valid labels,
and X outside the supplied half masks. Missing/disabled tags remain supported.
The decoder keeps stopped/live evidence separate from team evidence, uses
tracking before tags, and records transition/source/period-start diagnostics.

Half 1 is declared `live_at_entry`; half 2 waits for eligible E3 live/restart
evidence. When a `SET PIECES` / `Kick Off (Start)` tag exists in the current
period block, its first frame is only a lower eligibility bound: the tag never
proves that play is live. See the
[decision record](decisions/2026-10-23-e2-data-evidence-and-state-machine-design.md)
and [technical draft](TECHNICAL_DOCUMENT.md) for the implemented policy and
known limits.

## Remaining gates

1. Re-run the merged synthetic suite in the pinned environment and confirm
   hosted CI remains asset- and credential-free.
2. An authorised teammate runs the complete system locally and E4 validates
   the exact CSV. A second laptop independently reproduces identical CSV bytes.
3. Owners confirm method/training provenance; finalise the
   [technical draft](TECHNICAL_DOCUMENT.md) and [release package](RELEASE.md).
4. A repository admin re-checks protection/visibility and makes the repository
   public after the data/history audit. The last recorded inspection found
   unprotected main and a connected account without admin access; this refresh
   did not re-verify repository settings.
5. The designated human submitter uploads the frozen team-named file/document
   and records confirmation. Registered team name is not in checked context.

## Rules and ownership

Output all 199,319 tactical-frame labels: H Barcelona, A Athletic, D stopped
play, X no answer. Ranking uses spellF1. The documented deadline is November 17,
2026; verify updates through registration. Public five-minute labels are pipeline
checks only, never training, tuning, selection, or evidence of an accuracy gain.

Hosted AI/CI uses public schemas and synthetic inputs. Restricted assets,
extracts, arrays, predictions, and detailed manifests remain local and ignored.
Each laptop sets MTAH_DATA_DIR privately. Follow [TEAM_PLAN.md](../../TEAM_PLAN.md),
[INTERFACES.md](INTERFACES.md), [WORKFLOW.md](WORKFLOW.md), and the owner handoffs.
E1 owns data/export/CLI/contracts, E2 decoding, E3 priors, E4 features/validation,
and E5 integration/docs/CI. Azamat reviews E5. Shared files and reviewed commits,
not a chat session, are the team's memory.
