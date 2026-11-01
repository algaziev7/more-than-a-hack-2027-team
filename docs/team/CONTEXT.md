# Project context

Updated: 2026-10-26.

## What is merged

- The team repository is https://github.com/algaziev7/more-than-a-hack-2027-team.
  `origin` points there; `upstream` points to the organiser repository.
- PR #1 added Almaz's list-based tagging signals and 14 synthetic tests.
- PR #2 added Azamat's shared types, data loader, CSV exporter, setup checks,
  dependency lock, and prediction command. The command needs the future
  pipeline before it can produce predictions.
- Azamat reported a successful local data-loading check. Almaz reported that
  his original tagging helper produced 199,319 frames. These are user-reported
  execution checks, not measured possession accuracy.
- The original scorer, submission validator, public five-minute answer file,
  and baseline files are unchanged.

## Current branch work — not merged

`almaz/tagging-adapter` adds a direct connection between Almaz's tagging lists
and Azamat's `PriorData`. The call is:

```python
priors = build_tagging_priors(match.events, n_frames=len(match.frame))
```

All 54 relevant synthetic tests passed. The adapter is ready for pull-request
review and is not yet merged.
Details are in [Almaz's handoff](owners/almaz.md) and [TAGGING.md](TAGGING.md).

## Who owns each part

| Owner | Work |
|---|---|
| Azamat | Data, shared types, environment, and CSV export |
| Belek and Isken | State machine and its tests |
| Almaz | Event tags, restart clues, and later stoppage detection |
| Beks | Tracking features and evaluation |
| Goblin agents | Pipeline integration and docs, reviewed by Azamat |

Everyone uses their own laptop and task branch in one shared repository.
Each owner updates their own handoff. Do not treat work on a task branch as
merged work. Confirm other owners' current progress before taking over files.

## What remains

- Review and connect the tagging adapter.
- Build and connect tracking features, actual stoppage detection, the state
  machine, and the full prediction pipeline. Those modules are not present in
  the checkout inspected for this update.
- Run the complete pipeline locally, validate its exact CSV, and reproduce it
  on a second laptop. No complete team prediction has been verified here.
- Keep the technical document up to date as the method changes.

## Task and rules

Output 199,319 tactical-frame labels: H for Barcelona, A for Athletic, D for
stopped play, X for no answer. Official ranking uses spellF1. Submit a CSV,
a public reproducible code repository, and a short technical document.
The documented deadline is November 17, 2026; check organiser updates by email.

The public five minutes are only for pipeline checks, never for training,
tuning, or model selection. Use synthetic inputs in hosted AI sessions. Actual
match assets, extracts, and generated private arrays stay local and out of Git.
Each person sets their own MTAH_DATA_DIR. No shared document needs that path.

Read TEAM_PLAN.md for responsibilities, INTERFACES.md for field names,
WORKFLOW.md for branches and handoffs, and SETUP.md for the team environment.
