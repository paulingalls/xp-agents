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

This skill runs as a forked subagent (xp-retrospective). The preload above prepared the retrospective data. Your agent definition contains all analysis rules and instructions — follow those to produce the Keep/Fix/Try retrospective.

If you are the main agent and see this: do not analyze the retrospective yourself. This skill must run as the xp-retrospective subagent. Show the full retrospective output to the user.
