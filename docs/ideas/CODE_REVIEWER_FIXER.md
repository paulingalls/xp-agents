# Code Reviewer Fixer: Teammate-Based Fix Implementation

## Problem

The xp-code-reviewer identifies issues but has no good path for implementing fixes:

- **Fixing directly** (current): changes happen inside the review cycle with no independent review. The reviewer is both author and reviewer of the fix.
- **Handing back to main agent**: the agent already anchored on its decisions (it wrote the code, it already skipped simplify findings). Asking the author to review themselves doesn't produce independent judgment.
- **Recording as debt only**: loses the courage of fixing while context is fresh. Small fixes get deferred and forgotten.

## Proposed Solution

The code-reviewer becomes **read-only** — it produces findings but does not edit code. A dedicated fixer teammate (`claude -p` in a worktree) implements the fixes with a simplify-only review cycle. This gives fixes an independent review without creating infinite recursion.

### Key Design Decisions

1. **Code-reviewer is read-only.** It identifies, categorizes, and reports. It does not have Edit/Write tools. This cleanly separates the reviewer role from the implementer role.

2. **One fixer teammate per quality review cycle.** All findings are batched into a single prompt. Spawning multiple teammates for 2-5 small fixes is wasteful.

3. **Simplify-only review cycle for the fixer.** The fixer runs `/simplify` before committing but does NOT run `/xp-quality-review` or `/xp-security-triage`. This breaks the recursion (no quality review → no code-reviewer → no fixer → ...). Security triage runs after merge on the main agent, covering the fixer's changes.

4. **Regular CLI teammates (from /xp-assign) keep the full review cycle.** The simplify-only cycle is specific to fixer teammates spawned by the quality review skill. The distinction is: fixer teammates implement small scoped fixes from a reviewer's instructions; regular teammates implement full stories with design decisions.

5. **Temporary branch for the starting state.** The fixer needs to work on uncommitted changes. A WIP commit to a temp branch provides the starting state.

## Architecture

### Current Flow (quality review)

```
Main agent has uncommitted changes (post-simplify)
  → /xp-quality-review skill runs
  → Spawns xp-code-reviewer (Agent tool)
  → Code-reviewer reads code, produces findings
  → Code-reviewer fixes small things directly ← NO INDEPENDENT REVIEW
  → Code-reviewer records large things as debt
  → Quality review skill records summary
  → Main agent runs /xp-security-triage
  → Main agent commits
```

### Target Flow

```
Main agent has uncommitted changes (post-simplify)
  → /xp-quality-review skill runs
  → Creates temp branch, commits WIP state
  → Spawns xp-code-reviewer (Agent tool)
  → Code-reviewer:
      1. Reviews code, categorizes findings
      2. Records debt for large items (via append.sh)
      3. If actionable findings exist:
         a. Writes fixer prompt file
         b. Spawns fixer teammate via Bash (spawn_teammate.py in worktree from temp branch)
         c. Waits for fixer to complete
         d. Reports: what was fixed, what was skipped, fixer branch name
      4. Returns structured summary to quality review skill
  → Quality review skill receives summary
  → If fixer ran: main agent merges fixer branch
  → Main agent drops temp branch
  → Main agent runs /xp-security-triage (reviews everything including fixes)
  → Main agent commits
```

The code-reviewer owns the entire review+fix flow. The quality review skill just spawns it, merges the result, and continues the review cycle.

### Temp Branch Lifecycle

```
1. Code-reviewer creates temp branch:
   git checkout -b quality-review-wip-<session-hash>
   git add -A && git commit -m "WIP: pre-quality-review state"
2. Code-reviewer spawns fixer in worktree from this branch
3. Fixer commits fixes to its own branch
4. Code-reviewer reports fixer branch name to quality review skill
5. Quality review skill (main agent) merges fixer branch
6. Main agent drops temp branch:
   git branch -D quality-review-wip-<session-hash>
7. Continue with security triage and final commit
```

The WIP commit is ephemeral — it exists only to give the fixer worktree a valid starting state. It never gets pushed.

## Component Changes

### xp-code-reviewer Agent

**File:** `agents/xp-code-reviewer.md`

- Remove Edit, Write from tools — reviewer doesn't fix code directly
- Keep Bash — needed for `spawn_teammate.py`, `append.sh`, and git operations (temp branch)
- Tools: `Read, Grep, Glob, Bash`
- New responsibilities:
  1. Review code and categorize findings (unchanged)
  2. Record debt via `append.sh` (unchanged)
  3. Create temp branch and commit WIP state
  4. Write fixer prompt file with all actionable findings
  5. Spawn fixer teammate via `spawn_teammate.py --review-cycle simplify-only`
  6. Wait for fixer completion
  7. Return structured summary including fixer branch name

Output format:

```
## Fixer Results
Branch: fixer-quality-review-<hash>
Fixes applied: 3 of 4 (1 skipped — more complex than expected)

## Actionable Findings
1. [FIXED] [Simplicity] plugins/xp-agents/scripts/foo.py:42 — removed dead helper `_old_format()`
2. [FIXED] [Honesty] plugins/xp-agents/scripts/bar.py:15-20 — propagated FileNotFoundError
3. [FIXED] [Courage] plugins/xp-agents/scripts/baz.py:8 — removed legacy fallback
4. [SKIPPED] [Communication] plugins/xp-agents/scripts/qux.py — type narrowing requires 
   upstream changes, recorded as debt

## Debt (too large for this cycle)
- [recorded] Circular dependency between coordination.py and concerns.py
- [recorded] Type narrowing in qux.py requires upstream interface changes
```

### xp-quality-review Skill

**File:** `skills/xp-quality-review/SKILL.md`

Current steps: spawn reviewer → resolve plan concerns → act on findings → record summary.

New steps:
1. **Create temp branch** — commit WIP state (the code-reviewer needs this for the fixer worktree, but creating it before spawning the reviewer ensures it's ready)
2. **Spawn xp-code-reviewer** — reviews, spawns fixer if needed, returns summary with branch name
3. **Resolve plan concerns** — unchanged
4. **If fixer ran**: merge fixer branch, drop temp branch
5. **If no fixer**: drop temp branch
6. **Record summary**

The quality review skill becomes simpler — it delegates the review+fix orchestration to the code-reviewer and handles only the merge and cleanup.

### Fixer Teammate

The fixer is a regular `claude -p` process in a worktree, but with a **simplified review cycle**. Options for achieving this:

**Option A: Fixer-specific skill**

Create a `/quality-fix` skill that replaces the commit gate for the fixer's session. The skill runs `/simplify` only, skipping quality review and security triage. The fixer's session uses this skill instead of the normal commit flow.

**Option B: Environment-based review cycle override**

Set an environment variable (e.g., `XP_REVIEW_CYCLE=simplify-only`) when spawning the fixer. The commit gate (`pre_tool_bash.py`) reads this and only requires the simplify flag, skipping quality and security flags.

**Option C: Marker-based review cycle override**

Write a `.review-cycle-mode` marker to the SMM directory with the fixer's agent ID. The commit gate checks this marker and adjusts required flags per-agent.

**Recommendation: Option B** — simplest, no new files, no marker coordination. The env var is set by `spawn_teammate.py` (or `spawn_fixer.py`) and read by `pre_tool_bash.py`. It's scoped to the fixer's process — doesn't affect the main agent or regular teammates.

### spawn_teammate.py (or new spawn_fixer.py)

Needs to support:
- Setting `XP_REVIEW_CYCLE=simplify-only` in the fixer's environment
- Working from a specified branch (the temp branch) instead of HEAD
- Passing the structured findings as the prompt

Could be a flag on `spawn_teammate.py` (`--review-cycle simplify-only`) or a separate `spawn_fixer.py` that handles the lighter setup. A flag is simpler — reuses existing infrastructure.

### pre_tool_bash.py (commit gate)

Read `XP_REVIEW_CYCLE` env var. When set to `simplify-only`:
- Only require `simplify_done` flag
- Skip `quality_review_done` and `security_review_done` checks

Default (unset or `full`): current behavior — require all three flags.

## Fixer Prompt Structure

```
You are fixing code review findings. A code reviewer identified these issues
in the current codebase. Implement each fix.

## Findings to Fix

1. [Simplicity] plugins/xp-agents/scripts/foo.py:42
   Remove dead helper `_old_format()` — no remaining callers after refactor.

2. [Honesty] plugins/xp-agents/scripts/bar.py:15-20
   Catch-and-swallow hides FileNotFoundError. Propagate the error or log
   with full context (file path, operation attempted).

## Guidelines

- Fix each finding in order
- Run tests after each fix to verify nothing breaks
- Run /simplify before committing
- If a fix turns out to be more complex than expected, skip it and note why
- Commit all fixes together with a clear message

## SMM Directory
SMM_DIR=<path>
```

## Sizing and Thresholds

Not every quality review needs a fixer teammate. The overhead of spawning a `claude -p` process (~30 seconds startup, ~$0.30-0.50 per session) is justified only when there are substantive fixes.

**Spawn fixer when:**
- 2+ actionable findings, OR
- Any finding with severity "high"

**Skip fixer when:**
- 0-1 low-severity actionable findings (record as debt instead)
- All findings are already recorded as debt by the reviewer

The quality review skill makes this decision based on the reviewer's structured output.

## Recursion Prevention

The recursion chain is: commit → simplify → quality review → code-reviewer → fixer → commit → ...

Broken at two points:
1. **Fixer uses simplify-only review cycle** — no quality review, no code-reviewer, no fixer
2. **Code-reviewer is read-only** — even if somehow invoked inside the fixer's cycle, it can't make changes or spawn another fixer

## Security Coverage

The fixer's changes skip security triage inside the fixer's session. This is acceptable because:
1. The fixer implements specific, scoped instructions from a reviewer (not open-ended work)
2. Security triage runs on the main agent AFTER merging the fixer's branch — all changes are covered
3. The fixer's changes are typically small (rename, delete, restructure) not security-sensitive

## Open Questions

1. **Should the fixer use a custom agent definition?** A dedicated `xp-fixer` agent with scoped instructions ("you implement code review findings, nothing else") would prevent scope creep. Alternatively, `claude -p` with a good prompt file is simpler and doesn't require a new agent definition. The fixer's prompt is already highly scoped (specific findings with file:line and instructions).

2. **Can the code-reviewer reliably manage the fixer subprocess?** The code-reviewer is itself a subagent (spawned via Agent tool). It has Bash access and can run `spawn_teammate.py`. But it needs to wait for the fixer to complete — `spawn_teammate.py` with `teammate_output_filter.py` handles this in the existing teammate flow. The code-reviewer would run this synchronously (not `run_in_background`) and read the output.

3. **Temp branch creation timing.** The doc shows the quality review skill creating the temp branch before spawning the code-reviewer, but the code-reviewer could also create it itself. Creating it in the skill ensures it's ready; creating it in the reviewer keeps all git operations in one place. Either works — the skill approach is slightly safer since the reviewer might fail before creating the branch.

4. **What if the fixer fails?** If the fixer hits test failures or can't implement a fix, it should skip that finding and note why in its output. The code-reviewer reports partial success — unimplemented findings get recorded as debt.

## Files Affected

| File | Change |
|------|--------|
| `agents/xp-code-reviewer.md` | Remove Edit/Write tools, add structured findings format |
| `skills/xp-quality-review/SKILL.md` | Add temp branch, fixer spawn, merge steps |
| `scripts/spawn_teammate.py` | Add `--review-cycle` flag for simplify-only mode |
| `scripts/pre_tool_bash.py` | Read `XP_REVIEW_CYCLE` env var, adjust required flags |
| `tests/hooks/test_bash.py` | Test simplify-only review cycle mode |
| `tests/hooks/test_review_cycle.py` | Test quality review skill with fixer flow |
