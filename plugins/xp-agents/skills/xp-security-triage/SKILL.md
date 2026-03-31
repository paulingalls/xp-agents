---
name: xp-security-triage
description: >-
  Triage staged changes before committing. Shows the diff and clears
  the commit gate. If any code files changed, runs /security-review.
  Non-code-only changes (docs, config, CI) need no further action.
effort: high
allowed-tools:
  - Bash(*/skills/*/scripts/*)
  - Skill(security-review)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload_diff.sh`

The triage marker has been written and the commit gate is cleared. Check the staged changes above:

**If any code files changed** (not just docs, config, or CI metadata), run `/security-review`. This is a **built-in Claude Code command** — invoke it as `/security-review`, NOT as `xp-agents:security-review`. Security review is fast and catches issues that are easy to miss during implementation.

**If only non-code files changed** (documentation, CI/CD metadata, config formatting, .gitignore, etc.), no further action needed.
