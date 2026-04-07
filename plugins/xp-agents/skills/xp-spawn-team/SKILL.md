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

This skill runs as a forked subagent (xp-spawn-team). The preload above prepared the sprint and plan data. Your agent definition contains all analysis rules and instructions — follow those to produce spawn instructions.

If you are the main agent and see this: do not analyze team sizing yourself. This skill must run as the xp-spawn-team subagent. Show the full spawn instructions to the user.
