# Team instructions for AI coding sessions

Read `docs/team/CONTEXT.md`, `TEAM_PLAN.md`, `docs/team/INTERFACES.md`,
`docs/team/WORKFLOW.md`, and the assigned engineer's file in `docs/team/owners/`
before working. Read related owners' files when consuming their modules.

Owner handoffs: E1 `azamat.md`; E2 `belek_isken.md`; E3
`almaz.md`; E4 `beks.md`; E5 `goblin.md` (AI agents).
All are under `docs/team/owners/`. Azamat reviews E5 changes.

These documents describe a proposed implementation. Do not claim a planned
module, command, experiment, or result already exists. Check the code and Git status.

- Work on the assigned task branch and within its owned files. Propose shared
  interface changes before implementing them; notify affected owners in the PR.
- Preserve other people's uncommitted changes. Do not switch branches in a
  shared working directory or reset another person's work.
- Implement against the shared interfaces and synthetic fixtures so a missing
  local match bundle does not block code development.
- Read RULES.md and FAQ.md before work involving data or evaluation. The public
  five minutes are for pipeline checks only, never training, parameter tuning,
  model selection, or selecting a final submission.
- Do not create manual labels, corrections, or frame-specific rules for the
  competition match. External human-produced labels must concern other matches.
- The FAQ prohibits sending restricted competition data or extracts to hosted
  LLMs. Do not expose the match files, frames, tracking rows, private derived
  arrays, or confidential materials in model-visible tools or chat. Develop with
  public schemas and synthetic inputs; team members run restricted-data jobs
  locally and keep their outputs in ignored directories.
- Keep supplied evaluation code and baseline files intact. Add team code under
  `possession/`, `scripts/`, and `tests/` as described in the plan.
- Keep data, caches, model outputs, and local paths out of committed context.
  Use `data/`, `artifacts/`, `runs/`, or `.local/` for local material.
- In Claude Code, when a change is finished and ready to commit, run the
  `pre-commit-reviewer` subagent (`.claude/agents/`) on it first, and fix or
  report its blocking findings. Other agents: do an equivalent review using
  that file's checklist. A Claude Code hook (`.claude/hooks/require-review.sh`,
  needs `jq` and a POSIX shell such as Git Bash) refuses an unreviewed
  `git commit` until it is rerun with `CLAUDE_REVIEWED=1`. That marker is an
  honour system, not a lock.
- At each handoff, update the owner's file with the actual branch, completed
  work, tests and their results, blockers, decisions, and exact next step.
  Distinguish measured results from hypotheses and untested code.
- Never infer that another laptop or AI session has read this conversation.
  Committed files and reviewed code are the shared memory.
