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

## Data Loading

First, resolve the SMM path and read the current state:
```bash
SMM_DIR=$(${CLAUDE_PLUGIN_ROOT}/smm/init.sh)
```
Then use Read to load `$SMM_DIR/SHARED_MENTAL_MODEL.md`.

## Task

Review the plan in progress against the SMM state. Check plan size, TDD ordering, milestone boundaries, and decision conflicts. Record assumptions and draft decisions to the event log.
