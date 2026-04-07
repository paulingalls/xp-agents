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

This skill should run as a forked subagent (xp-spawn-team). Your agent definition contains all instructions — follow them, record the result, and then report back your full findings to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-spawn-team subagent. Show the full output to the user.
