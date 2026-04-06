---
name: xp-run-sprint-retro
description: >-
  Sprint-level retrospective. Analyzes cross-session patterns, sizing accuracy,
  and velocity across the sprint. Produces sprint Keep/Fix/Try.
  Use after sprint review completes.
effort: high
context: fork
agent: xp-agents:xp-sprint-retro
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Analyze the sprint data above. Review cross-session patterns, assess sizing accuracy, and produce sprint-level Keep/Fix/Try.
