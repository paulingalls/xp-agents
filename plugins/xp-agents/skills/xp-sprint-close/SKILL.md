---
name: xp-sprint-close
description: >-
  Push the sprint branch, fork xp-close-reviewer for cross-cutting review,
  and merge into the target with cleanup. Auto-invoked at the end of
  /xp-sprint-review; degrades gracefully when gh is unavailable.
allowed-tools:
  - Read
  - Write
  - Bash
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */scripts/branching.py *)
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Sprint Close

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, `WORKTREE_CLEAN`, and `REVIEW_INPUT`. Slice B will fill
in the full step-by-step orchestration (push → PR-or-skip → fork
close-reviewer → present → AskUserQuestion → merge --no-ff → cleanup).
For now this skeleton exists so the loader can load the skill while the
preload contract is locked under test.
