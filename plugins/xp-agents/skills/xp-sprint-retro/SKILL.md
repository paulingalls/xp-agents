---
name: xp-sprint-retro
description: >-
  Sprint-level retrospective. Analyzes cross-session patterns, sizing accuracy,
  and velocity across the sprint. Produces sprint Keep/Fix/Try.
  Use after sprint review completes.
effort: high
context: fork
agent: xp-agents:xp-sprint-retro
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(cat *| python3 */save_retrospective.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Analyze the sprint data above. Review cross-session patterns, assess sizing accuracy, and produce sprint-level Keep/Fix/Try.
