# Project context

Updated: 2026-10-23. Status: planning complete; team implementation not started.

## Confirmed facts

- Five equally experienced engineers, separate laptops, AI-assisted development.
- User reports having all match assets. Actual local bundle location is unresolved.
- The downloaded README supplied by the user matches the
  starter's data-layout instructions; it is not an asset manifest or proof that
  the bundle is extracted. Expected tactical/broadcast directories were not in
  that folder or its data/ child at the time of inspection.
- This checkout's data/ contains its README only; MTAH_DATA_DIR was unset.
- Private team repository created: https://github.com/algaziev7/more-than-a-hack-2027-team.
  The team remote is origin; the organiser repository is preserved as upstream.
  Collaborator access still needs to be configured using the members' GitHub usernames.
  No prediction implementation or full-data execution has been performed.
- Existing source includes loaders, baselines, official scorer, validator, and
  five public minutes of GT. Public GT cannot be used to train/tune/select models.
- Required output: 199319 tactical frames, H/A/D/X. Rank: spellF1. Deliverables:
  CSV, public reproducible code, short technical document.
- Repository deadline: 2026-11-17, subject to official organiser updates.

## Working decisions

- One team repository; separate clones and short task branches.
- E1: Azamat (data/infra). E2: Belek and Isken (state machine).
  E3: Almaz (dead ball/tags). E4: Beks (features/evaluation).
  E5: Goblin (AI agents for integration/docs), reviewed by Azamat.
  Actual available hours remain unconfirmed.
- First increment uses tactical tracking and tagging; video and broadcast are
  optional extensions after a valid integrated submission exists.
- Contracts and synthetic examples first; all five work concurrently.
- Initial estimate: 32 focused hours per person; first integration by hour 12.
- Each engineer owns their handoff; E5 updates this integrated context.

## Current blockers / next actions

1. Confirm available hours and divide E2 tasks between Belek and Isken.
2. Add team collaborators, clone the team repository, and start task branches.
3. E1 locates the actual bundle root on each laptop and verifies local setup.
4. Team agrees on INTERFACES.md; E1 creates contracts/fixtures.
5. Start the first-hour tasks in TEAM_PLAN.md and integrate early.

## Evidence and limitations

This plan is based on public repository docs/code and the requested downloaded
README. Restricted match contents were not read. No new prediction code, score,
performance improvement, environment lock, or reproducibility claim exists yet.
All proposed module paths and team CLI commands still need implementation.

For role details read TEAM_PLAN.md. For cross-laptop handoffs and AI startup read
WORKFLOW.md. For interfaces read INTERFACES.md. Update this file only after
reviewed integration, keeping branch-only progress in owners/*.md.
