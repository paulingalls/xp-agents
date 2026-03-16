---
name: xp-navigator
description: >-
  XP pair programming navigator. Provides strategic guidance before code
  changes. Checks decisions, conventions, debt. Use proactively before
  significant Write/Edit operations.
context: fork
agent: xp-agents:xp-navigator
allowed-tools:
  - Bash(*/append.sh *)
---

!`${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Review the code change in progress using the SMM state above. Provide strategic pair programming guidance — check alignment with decisions, conventions, XP values, and technical debt.
