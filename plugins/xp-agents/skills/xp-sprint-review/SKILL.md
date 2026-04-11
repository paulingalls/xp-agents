---
name: xp-sprint-review
description: >-
  Review the completed sprint. Compares what shipped vs planned, updates
  execution_plan.md milestones with delivered status, and records sprint
  velocity. Use when all stories are done or deferred.
effort: high
context: fork
agent: xp-agents:xp-sprint-reviewer
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill should run as a forked subagent (xp-sprint-reviewer). Your agent definition contains all instructions — follow them, record the result, and then report back your full findings to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-sprint-reviewer subagent. The subagent result is returned as a tool result which is NOT visible to the user — you must output the key findings as text in your response.
