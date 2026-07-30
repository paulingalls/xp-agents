---
name: xp-system-context
description: >-
  Create or update system_context.json: analyse the codebase to describe the
  product, architecture and technical constraints.
effort: high
context: fork
agent: xp-agents:xp-system-analyzer
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/smm/system_context_cli.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill should run as a forked subagent (xp-system-analyzer). Your agent definition contains all instructions — follow them, analyze the codebase, write system_context.json, and then report back your summary to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-system-analyzer subagent. The subagent result is returned as a tool result which is NOT visible to the user — you must output the key findings as text in your response.
