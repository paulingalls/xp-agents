---
name: xp-security-triage
description: >-
  Triage staged changes before committing. Shows the diff and clears
  the commit gate. If any code files changed, runs /security-review.
  Non-code-only changes (docs, config, CI) need no further action.
effort: high
context: fork
agent: xp-agents:xp-security-reviewer
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Skill(security-review)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload_diff.sh`

Run `/security-review` on the changes above (staged, unstaged, and new files).
