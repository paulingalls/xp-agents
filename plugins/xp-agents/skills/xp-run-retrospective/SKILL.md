---
name: xp-run-retrospective
description: >-
  Run the session retrospective. Keep/Fix/Try analysis with XP values as lenses.
  Use at session start when retrospective data is available.
effort: high
context: fork
agent: xp-agents:xp-retrospective
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill should run as a forked subagent (xp-retrospective). Your agent definition contains all instructions — follow them, record the result, and then report back your full findings to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-retrospective subagent. Show the full output to the user.
