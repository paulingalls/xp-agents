---
name: xp-subagent-reviewer
description: >-
  XP subagent reviewer. Holistic output review for convention adherence,
  complexity, and decision alignment. Runs in background.
context: fork
agent: xp-agents:xp-subagent-reviewer
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(git diff *)
---

## Data Loading

First, resolve the SMM path and read the current state:
```bash
SMM_DIR=$(${CLAUDE_PLUGIN_ROOT}/smm/init.sh)
```
Then use Read to load `$SMM_DIR/SHARED_MENTAL_MODEL.md`. Also run `git diff HEAD~1 --stat` to see recent changes.

## Task

Review the subagent's recent output against the SMM state. Check convention adherence, complexity, and alignment with project decisions. Record concerns to the event log.
