---
name: xp-subagent-reviewer
description: >-
  XP subagent reviewer. Holistic output review for convention adherence,
  complexity, and decision alignment. Runs in background.
context: fork
agent: xp-agents:xp-subagent-reviewer
allowed-tools:
  - Bash(*/append.sh *)
---

!`${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Review the subagent's recent output against the SMM state above. Check convention adherence, complexity, and alignment with project decisions. Record concerns to the event log.
