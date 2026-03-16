---
name: xp-retrospective
description: >-
  XP retrospective analyst. Keep/Fix/Try analysis with XP values as lenses.
  Use at session start when retrospective data is available.
context: fork
agent: xp-agents:xp-retrospective
allowed-tools:
  - Read
  - Write
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(python3 */materialize.py)
---

!`${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Analyze the retrospective data above using the Keep/Fix/Try framework with XP values as lenses. Record findings to the event log and retrospectives directory.
