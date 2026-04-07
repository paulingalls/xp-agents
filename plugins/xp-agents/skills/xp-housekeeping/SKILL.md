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

This skill runs as a forked subagent (xp-housekeeper). The preload above prepared the curation data. Your agent definition contains all curation rules and instructions — follow those to curate the five-pillar SMM.

If you are the main agent and see this: do not curate the SMM yourself. This skill must run as the xp-housekeeper subagent.
