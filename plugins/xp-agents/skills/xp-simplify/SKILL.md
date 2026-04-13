---
name: xp-simplify
description: >-
  Inline code review covering code reuse, code quality, and efficiency.
  Single-pass alternative to /simplify that works without spawning sub-agents.
  Use in worktree subagents (xp-teammate) where nested agent spawning is
  prohibited by the platform.
effort: high
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(python3 -m unittest *)
  - Bash(ruff format *)
  - Bash(ruff check *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Code Simplification Review

You are performing a code review on the uncommitted changes shown in the preload above. Review across three dimensions sequentially, then fix every finding.

## Step 1: Identify Changed Files

From the preload diff, list every file that has been modified. Use `Read` to load the full content of each changed file — you need the complete context, not just the diff hunks.

## Step 2: Code Reuse

For each changed file, search for existing utilities that could replace new code:

- Use `Grep` to search the codebase for functions with similar names or signatures to what was added.
- Use `Glob` to find related utility modules (e.g., `**/utils.py`, `**/helpers.py`, `**/_common.py`).
- Flag any duplicated logic — if a function already exists that does the same thing, the new code should call it.
- Flag inline logic that reimplements what an existing utility provides.

## Step 3: Code Quality

Review the changed code for quality issues:

- **Redundant state** — variables that duplicate information available elsewhere.
- **Parameter sprawl** — functions taking too many arguments; group into a config object or dataclass.
- **Copy-paste variations** — similar code blocks that differ only slightly; extract a shared function.
- **Leaky abstractions** — implementation details exposed through interfaces.
- **Stringly-typed code** — using strings where enums, constants, or typed objects would be safer.
- **Unnecessary comments** — comments that describe what the code does rather than why.
- **Mixed responsibilities** — functions or modules doing more than one thing.

## Step 4: Efficiency

Review the changed code for efficiency issues:

- **Unnecessary work** — computations whose results are never used, or repeated computations that could be cached.
- **Missed concurrency** — sequential operations that could run in parallel.
- **Hot-path bloat** — expensive operations on frequently-called paths.
- **No-op updates** — writes that don't change anything (e.g., writing same value to file).
- **Overly broad operations** — reading entire files when only a few lines are needed, scanning all events when a filtered subset suffices.
- **Memory issues** — loading large data structures into memory when streaming would work.

## Step 5: Fix Every Finding

For each finding from Steps 2-4:

**Apply the fix directly.** Edit the files to address the issue. This is the default — every finding gets fixed.

If a fix is genuinely too large for this review (would require restructuring multiple modules or changing public APIs), record it as technical debt:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "debt" \
  --agent "xp-simplify" \
  --content "Description of what needs fixing and why it cannot be fixed now" \
  --files '["path/to/file.py"]'
```

Recording debt requires a concrete reason. These are NOT valid reasons to skip a fix:
- "It's consistent with existing code" — if existing code is wrong, fix both.
- "It's a design choice" — design choices can be wrong.
- "Low severity" — low severity is not zero severity.
- "Pre-existing issue" — if the code is open in your editor, fix it now.
- "Not our change" — you touched the file, you own it.

## Step 6: Run Tests

After making fixes, run the test suite to verify nothing is broken:

```bash
python3 -m unittest discover -s <test-dir> -p "test_*.py" -v
```

If tests fail, fix the regression before proceeding.

## Step 7: Record Summary

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" \
  --agent "xp-simplify" \
  --content "Simplify review complete. Fixed: [list]. Debt recorded: [list]. Clean: [list]." \
  --working-on '[]'
```
