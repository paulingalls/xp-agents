---
name: xp-housekeeping
description: >-
  Five-pillar SMM curation. Reads structured curation data and existing SMM,
  applies LLM judgment to curate Intent, Constraints, Risks, Wisdom, and Sprint.
  Writes curated SMM and updates curation watermark.
effort: high
context: fork
agent: xp-agents:xp-housekeeper
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(cat *| python3 */save_smm.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill should run as a forked subagent (xp-housekeeper). Your agent definition contains all instructions — follow them, record the result, and then report back your summary to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-housekeeper subagent. Show the full output to the user.
