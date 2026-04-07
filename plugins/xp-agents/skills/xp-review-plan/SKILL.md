---
name: xp-review-plan
description: >-
  Review the current plan. Checks plan size, TDD ordering, milestone boundaries,
  and decision conflicts. Use after planning completes.
effort: high
context: fork
agent: xp-agents:xp-plan-reviewer
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill should run as a forked subagent (xp-plan-reviewer). Your agent definition contains all instructions — follow them, record the result, and then report back your full findings to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-plan-reviewer subagent. Show the full output to the user.
