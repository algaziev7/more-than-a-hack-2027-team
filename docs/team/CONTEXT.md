# Project context

Updated: 2026-11-01.

## What is merged

- Team repo: https://github.com/algaziev7/more-than-a-hack-2027-team.
  origin is the team repo; upstream is the organiser repo.
- PR #1: Almaz's event-tag clues and synthetic tests.
- PR #2: Azamat's loader, shared types, export, setup, and invocation code.
- PR #3: Belek and Isken's validation plan. This is documentation; the state
  machine itself is not in this checkout.
- PR #4: Almaz's tagging adapter returns Azamat's PriorData format.
- Azamat and Almaz reported successful local data-loading runs. Those confirm
  execution, not possession accuracy. No private outputs were read here.
- The official scorer, validator, public answer file, and baselines are unchanged.

## Current branch — not merged

`almaz/dead-ball-priors` adds `possession.dead_ball.build_priors(match, features,
config)`. It returns tagging clues plus conservative stopped/live-play evidence
and a motion-supported restart pulse. FeatureData is optional; no new shared
fields or feature names are introduced.

The full synthetic suite passed 97 tests, including 33 new scenarios. Review,
authorised local real-data execution, and integrated accuracy checks are still
pending. Read [DEAD_BALL.md](DEAD_BALL.md) and [Almaz's handoff](owners/almaz.md).

## Owners

| Person | Work |
|---|---|
| Azamat | Data, shared types, environment, and export |
| Belek and Isken | Possession state machine and its tests |
| Almaz | Event tags and stoppage/restart evidence |
| Beks | Tracking features and evaluation |
| Goblin agents | Integration and docs; Azamat reviews |

One shared repo, separate laptop clones and task branches. Each owner maintains
their handoff. A branch implementation is not integrated until reviewed/merged.

## Remaining work

- Review the stoppage module and connect its evidence to the state machine.
- Add Beks's features, the state machine, and the complete pipeline. These are
  not present on main inspected for this update. Check teammates' latest work
  before editing their files.
- Run the complete system, validate its CSV, and reproduce it on another laptop.
  No complete team prediction or measured accuracy improvement is established.
- Keep the technical document aligned with the implemented method.

## Task and rules

Output 199,319 tactical-frame labels: H Barcelona, A Athletic, D stopped play,
X no answer. Ranking uses spellF1. Submit a CSV, public reproducible repository,
and short technical document. Documented deadline: November 17, 2026; check
organiser updates through the registration channel.

The public five-minute answer file is for pipeline checks, never training,
tuning, or model selection. Hosted AI/CI use synthetic inputs. Actual assets,
extracts, private arrays, and detailed reports stay local and outside Git.
Each person sets MTAH_DATA_DIR locally.

Read TEAM_PLAN.md for ownership, INTERFACES.md for shared fields, WORKFLOW.md
for branches/handoffs, and SETUP.md for the team environment.
