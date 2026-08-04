---
name: xp-scaffold-worktree
description: >-
  Scaffold stack.worktree_bootstrap: measure a fresh worktree's gap for a
  declared command, propose a candidate, verify it closed the gap, refuse
  otherwise.
allowed-tools:
  - Read
  - Grep
  - Glob
  - AskUserQuestion
  - Bash(python3 */scripts/worktree_differential.py *)
  - Bash(python3 */smm/system_context_cli.py *)
  - Bash(git rev-parse *)
---

# Scaffold Worktree Bootstrap

> **Sequential discipline.** Run Steps 0-8 in order, one step per turn — never
> batch the Step 4 `AskUserQuestion` with the Step 5 verification it authorizes.

Entry point for `/xp-scaffold-worktree`. **Inline — do not fork a subagent.**

Skeleton — steps land in the next increment.
