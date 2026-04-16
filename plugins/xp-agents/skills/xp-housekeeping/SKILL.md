---
name: xp-housekeeping
description: >-
  Four-pillar SMM curation. Reads structured curation data and existing SMM,
  applies LLM judgment to curate Intent, Constraints, Risks, and Wisdom.
  Writes curated SMM and updates curation watermark.
effort: high
context: fork
agent: xp-agents:xp-housekeeper
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(echo *| python3 */smm_cli.py *)
  - Bash(python3 */smm_cli.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill should run as a forked subagent (xp-housekeeper). Your agent definition contains all instructions — follow them, render the curated SMM, and report back both the rendered SMM and your change summary to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-housekeeper subagent. The subagent returns the rendered SMM + change summary as a tool result which is NOT visible to the user — you must output both as text in your response.
