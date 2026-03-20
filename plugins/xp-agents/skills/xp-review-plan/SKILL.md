---
name: xp-review-plan
description: >-
  Review the current plan. Checks plan size, TDD ordering, milestone boundaries,
  and decision conflicts. Use after planning completes.
effort: high
context: fork
agent: xp-agents:xp-plan-reviewer
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Review the plan in progress against the SMM state above. Check plan size, TDD ordering, milestone boundaries, and decision conflicts. Record assumptions and draft decisions to the event log.
