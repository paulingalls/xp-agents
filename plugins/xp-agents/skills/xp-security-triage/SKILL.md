---
name: xp-security-triage
description: >-
  Run /security-review on pending changes for ad-hoc mid-flight checks.
  The standard cycle is covered by Tier 2 (/xp-accept) and Tier 3 (close).
effort: high
context: fork
agent: xp-agents:xp-security-reviewer
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload_diff.sh`

This skill should run as a forked subagent (xp-security-reviewer). Your agent definition contains all instructions — follow them, record the result, and then report back your full findings to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-security-reviewer subagent. The subagent result is returned as a tool result which is NOT visible to the user — you must output the key findings as text in your response.
