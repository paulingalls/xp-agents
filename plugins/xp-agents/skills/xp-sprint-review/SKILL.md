---
name: xp-sprint-review
description: >-
  Review the completed sprint. Compares what shipped vs planned, updates
  product_spec.md with delivery markers, and records sprint velocity.
  Use when all stories are done or deferred.
effort: high
context: fork
agent: xp-agents:xp-sprint-reviewer
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill runs as a forked subagent (xp-sprint-reviewer). The preload above prepared the sprint data. Your agent definition contains all review rules and instructions — follow those to review the sprint.

If you are the main agent and see this: do not review the sprint yourself. This skill must run as the xp-sprint-reviewer subagent.
