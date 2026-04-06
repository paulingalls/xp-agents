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

Review the sprint data above. Analyze what shipped vs planned, update product_spec.md with delivery markers, and record the sprint end event.
