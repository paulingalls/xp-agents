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

This skill runs as a forked subagent (xp-plan-reviewer). The preload above prepared the plan and SMM data. Your agent definition contains all review checklists and instructions — follow those to review the plan.

If you are the main agent and see this: do not review the plan yourself. This skill must run as the xp-plan-reviewer subagent. Show the full review output to the user.
