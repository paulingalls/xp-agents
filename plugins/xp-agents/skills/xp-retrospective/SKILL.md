---
name: xp-retrospective
description: >-
  XP retrospective analyst. Keep/Fix/Try analysis with XP values as lenses.
  Use at session start when retrospective data is available.
context: fork
agent: xp-agents:xp-retrospective
allowed-tools:
  - Bash(*/append.sh *)
  - Write
---

!`${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Analyze the retrospective data above using the Keep/Fix/Try framework with XP values as lenses. Record findings to the event log and retrospectives directory.
