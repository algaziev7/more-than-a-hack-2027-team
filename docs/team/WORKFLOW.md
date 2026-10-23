# Five laptops, one repository, persistent context

## Repository setup

The private team repository is
https://github.com/algaziev7/more-than-a-hack-2027-team. It preserves the organiser
starter's history and licence. Add the other members as collaborators before
they clone it. In the maintainer checkout, origin is the team repository and
upstream is the organiser repository.

```bash
git clone https://github.com/algaziev7/more-than-a-hack-2027-team.git
cd more-than-a-hack-2027-team
git remote add upstream https://github.com/metrica-sports/more-than-a-hack-2027.git
```

These commands set up a new developer laptop. Each laptop has its own local environment
and MTAH_DATA_DIR. The final submission repository must be public; keep restricted
files out of the repository and its history throughout development.

## Branches and ownership

Create a short branch per task, for example `e1/data-contract`, `e2/state-v1`,
`e3/restarts-v1`, `e4/features-v1`, `e5/pipeline-v1`. Keep branches small enough to
review and integrate each session. Do not use a single shared working directory
for multiple agents or keep five branches apart until the final day.

```bash
git switch main
git pull --ff-only origin main
git switch -c e2/state-v1
# Work, test, and update docs/team/owners/belek_isken.md.
git add possession/state_machine.py docs/team/owners/belek_isken.md
# Stage your relevant tests/config explicitly as well.
git diff --cached
git commit -m "Add possession hysteresis with synthetic transition tests"
git push -u origin e2/state-v1
```

The paths above are an example for E2 once those files exist. Check staged files
before committing; do not blindly stage generated outputs. Open a PR to team main
and request the reviewer assigned in TEAM_PLAN.md. The PR lists behavior, tests,
contract changes, limitations, and the updated handoff. One approval for shared
logic/contracts. Do not commit directly to main during parallel development.

To absorb merged work into a published task branch, commit your own changes,
fetch, then merge `origin/main`. Prefer this to rewriting shared branch history.
Resolve conflicts with the relevant file owner. No force pushes to main.

## Shared memory

| File | Writer | Purpose |
|---|---|---|
| AGENTS.md | E5, reviewed by team | Instructions every AI session reads |
| TEAM_PLAN.md | E5, team agreement | Roles, scope, milestones, acceptance |
| INTERFACES.md | E1, consumer review | Stable module contract |
| CONTEXT.md | E5 at integration checkpoints | What is actually integrated and next |
| owners/azamat.md ... owners/goblin.md | Each owner edits their own | Work in progress and handoff |
| decisions/*.md | Decision author, affected-owner review | Why a significant choice was made |
| experiments/*.md | Experiment author | Hypothesis, evidence source, outcome |

Do not have all five people rewrite one status file. Use separate owner files and
uniquely named decision/experiment files such as `2026-10-24-e2-hysteresis.md`.
Keep new entries brief and link to commits/PRs instead of copying code or chats.
The latest merged CONTEXT is the integrated truth; a branch handoff describes work
that may not yet be integrated. An unpushed file is invisible to other laptops.

At each meaningful checkpoint (roughly 60–90 minutes or a completed task):

1. Run relevant synthetic checks and record the actual outcome.
2. Update your owner file: branch, completed work, tests, blockers, changed
   contracts, next exact action, and relevant commit/PR reference.
3. Commit code and its handoff together, then push. Work-in-progress may be pushed
   to your branch with its limitations stated; do not mark it accepted on main.
4. Tell affected owners which PR/branch changed. Merge reviewed increments early.

Have a 10-minute sync at the start and midpoint of each joint work session. Ask
each owner for completed work, next task, blockers, and interface changes. E5
updates CONTEXT after integration. Rotate facilitation to share coordination load.

## Starting or resuming an AI session

Fetch/pull the relevant code before starting. Give the assistant this prompt,
replacing the owner ID, branch, and task:

> You are helping Engineer E2 on branch e2/state-v1. Read AGENTS.md,
> docs/team/CONTEXT.md, TEAM_PLAN.md, docs/team/INTERFACES.md,
> docs/team/WORKFLOW.md, and docs/team/owners/belek_isken.md. Inspect Git status and the
> actual implementation. Continue the next task in the owner handoff. Respect
> ownership and competition rules, use synthetic inputs in hosted AI tools, and
> update my handoff with completed work, actual verification, and the next step.
> Do not assume planned commands or modules exist. Do not overwrite others' work.

For tools that do not automatically read AGENTS.md, explicitly include that read
instruction in the session or configure the tool's project instructions to point
to it. Git synchronises files; it does not synchronise chats or guarantee an AI
has read them. Before switching AI models, update and save the same handoff.

## Experiment records and legal validation

Each record states: owner, code commit, config identity, hypothesis, data source,
whether labels were used, how parameters were chosen, command, measured result,
limitations, and decision. Never commit restricted tracking or frame extracts.

- Synthetic cases: logic/regression testing, not proof of competition accuracy.
- Other-match labels: legal development/selection with provenance and access.
- Public five minutes: pipeline sanity check only; no variant selection or tuning.
- Unlabelled match diagnostics: explain behavior, not an accuracy measurement.

Bootstrap comparisons belong on suitable other-match evaluation data. Public
window bootstrap can describe uncertainty, but cannot justify selecting a model
from that window. Keep any private run manifests, arrays, clips, debug views,
and output CSVs in ignored runs/ or artifacts/. Clear notebook outputs before
committing. Confidential or restricted materials cannot enter hosted LLM chats
or model-visible tool output, as stated in FAQ.md.

## Release

Freeze a code commit/config. E1 runs the regeneration command; E4 validates the
exact CSV. E5 independently reproduces it on another laptop and compares hashes.
Every owner supplies their method/limitation paragraph. E5 assembles the technical
document, checks Git history for accidental data, and prepares the public repo.
The designated human submitter uploads and records confirmation. Context is
updated with the submitted version; later experiments cannot overwrite it.
