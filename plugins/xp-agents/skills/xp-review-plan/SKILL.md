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

## Size-Floor Rule

M-sized stories must not exceed 15 projected files (file_domain + projected test siblings). If any M story exceeds this threshold, the preload emits a `size_floor_violations` array and the reviewer blocks approval. Stories at that scale must be sized L or split.

Projection heuristic: each `plugins/xp-agents/scripts/<name>.py` in the file_domain projects +1 test sibling. Skill/agent markdown files project 0.

This skill should run as a forked subagent (xp-plan-reviewer). Your agent definition contains all instructions — follow them, record the result, and then report back your full findings to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-plan-reviewer subagent. The subagent result is returned as a tool result which is NOT visible to the user — you must output the key findings as text in your response.
