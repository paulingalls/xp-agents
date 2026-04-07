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

This skill runs as a forked subagent (xp-sprint-retro). The preload above prepared the sprint data. Your agent definition contains all analysis rules and instructions — follow those to produce the sprint-level Keep/Fix/Try.

If you are the main agent and see this: do not analyze the sprint retrospective yourself. This skill must run as the xp-sprint-retro subagent.
