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

Curate the five-pillar SMM using the preloaded curation data. Read .curation-input.json, apply judgment to curate all pillars (Intent, Constraints, Risks, Wisdom, Sprint), record resolutions, and write the updated SMM via save_smm.py.
