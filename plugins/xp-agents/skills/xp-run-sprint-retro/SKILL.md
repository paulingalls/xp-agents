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

This skill should run as a forked subagent (xp-sprint-retro). Your agent definition contains all instructions — follow them, record the result, and then report back your full findings to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-sprint-retro subagent. Show the full output to the user.
