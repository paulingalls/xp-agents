---
name: xp-spawn-team
description: >-
  Analyze the current plan and sprint, then output structured instructions
  for spawning an Agent Team. Identifies file domains, parallel task groups,
  and team sizing. Does NOT spawn the team directly.
effort: high
context: fork
agent: xp-agents:xp-spawn-team
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

Analyze the sprint and plan data above. Identify file domains, parallel task groups, and team sizing. Output structured spawn instructions for the lead.

**Show the full spawn instructions to the user** — do not summarize or act on them silently.
