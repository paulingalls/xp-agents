---
name: xp-plan-reviewer
description: >-
  XP plan reviewer. Highest-leverage review -- checks plan size, TDD ordering,
  milestone boundaries, decision conflicts. Use after planning completes.
context: fork
agent: xp-agents:xp-plan-reviewer
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
---

!`${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Review the plan in progress against the SMM state above. Check plan size, TDD ordering, milestone boundaries, and decision conflicts. Record assumptions and draft decisions to the event log.
