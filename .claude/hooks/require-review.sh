#!/bin/sh
# PreToolUse hook: block Claude's `git commit` until the pre-commit-reviewer has run.
# Claude marks a reviewed commit by prefixing it with CLAUDE_REVIEWED=1 (a nudge, not a lock).
# Only commands Claude runs pass through here; terminal and `!` commits are not affected.
command -v jq >/dev/null || { echo "require-review: jq not found, review not enforced" >&2; exit 1; }
command=$(jq -r '.tool_input.command // empty')
case "$command" in *CLAUDE_REVIEWED=1*) exit 0 ;; esac
# `git [global options] commit` run as a command, allowing env-var prefixes, a path to git,
# and common wrappers (time, env, sudo, ...). Misses `bash -c "git commit"`.
pattern='(^|[;&|({!]|(^|[[:space:]])(then|do|else|time|exec|env|sudo|xargs|command))[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*([^[:space:];&|]*/)?git([[:space:]]+(-[Cc][[:space:]]+("[^"]*"|[^[:space:]]+)|--[A-Za-z][^[:space:]]*))*[[:space:]]+commit([^-[:alnum:]_]|$)'
if printf '%s\n' "$command" | grep -Eq "$pattern"; then
  jq -n '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny",
    permissionDecisionReason: "Before committing, run the pre-commit-reviewer subagent on these changes (Agent tool, subagent_type \"pre-commit-reviewer\"). Fix or report any blocking findings to the user, then rerun the same commit prefixed with CLAUDE_REVIEWED=1."}}'
fi
exit 0
