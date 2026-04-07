---
name: xp-security-triage
description: >-
  Triage staged changes before committing. Shows the diff and clears
  the commit gate. If any code files changed, runs /security-review.
  Non-code-only changes (docs, config, CI) need no further action.
effort: high
context: fork
agent: xp-agents:xp-security-reviewer
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload_diff.sh`

This skill runs as a forked subagent (xp-security-reviewer). The preload above prepared the diff data. Your agent definition contains all triage rules and instructions — follow those to triage the changes.

If you are the main agent and see this: do not triage the changes yourself. This skill must run as the xp-security-reviewer subagent.
