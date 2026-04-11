---
name: xp-system-context
description: >-
  Create or update system_context.md — autonomous codebase analysis that
  produces a thorough system description. Reads project structure, CLAUDE.md,
  and key source files to synthesize product overview, architecture, and
  technical constraints. Use standalone or invoked by /xp-plan.
effort: high
context: fork
agent: xp-agents:xp-system-context
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/scripts/save_planning_doc.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill should run as a forked subagent (xp-system-context). Your agent definition contains all instructions — follow them, analyze the codebase, write system_context.md, and then report back your summary to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-system-context subagent. The subagent result is returned as a tool result which is NOT visible to the user — you must output the key findings as text in your response.
