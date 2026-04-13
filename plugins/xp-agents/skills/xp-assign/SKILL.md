---
name: xp-assign
description: >-
  Analyze plan steps, decide execution mode (solo vs worktree subagents),
  and either proceed solo or spawn xp-teammate agents for parallel execution.
  Auto-run after planning completes.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Work Assignment

Analyze the plan and decide how to execute: solo (sequential) or with worktree-isolated subagents (parallel).

## Pre-flight Checks

1. If `PLAN_FILE` was not provided — output: "No plan file found. Enter plan mode and create a plan first." Stop.
2. Read the plan file at `PLAN_FILE` path.
3. If `SPRINT_FILE` was provided, read it for story context (optional — for status tracking only).
4. Analyze the plan's steps/tasks for parallelization potential.

## Mode Selection

Evaluate the plan steps and choose a mode:

**Solo** (sequential execution by the lead) when ANY of these apply:
- Plan steps have sequential dependencies between them
- Plan steps target overlapping files
- The plan is small (3 or fewer steps)

**Worktree subagents** (parallel execution) when ALL of these apply:
- 2+ independent step groups with no dependencies between them
- Steps target non-overlapping files
- Steps are substantial enough to justify coordination overhead

Present the recommendation to the user via `AskUserQuestion`:
- **Mode** (Solo or Worktree Subagents) with rationale
- For worktree mode: which step groups run in parallel, which are sequential

## Solo Mode

If solo: output "Proceeding with solo execution." and stop. The lead continues working on steps sequentially — no additional orchestration needed.

## Worktree Subagent Mode

For each parallel step group, spawn an `xp-teammate` agent:

```
Agent({
  description: "Step N: <title>",
  subagent_type: "xp-teammate",
  isolation: "worktree",
  run_in_background: true,
  prompt: "<spawn prompt below>"
})
```

### Spawn Prompt Template

Each spawn prompt must be self-contained — the teammate has no context beyond what you provide:

```
You are implementing step N: <title>

## Context
<inlined design context from the plan step>

## File Domain
<list of files this step exclusively owns>

## What to Change
<detailed changes from the plan step>

## Acceptance Criteria
<derived from the plan step's goals>

## Interface Contracts
<shared boundaries with other steps, if any>

## SMM Directory
SMM_DIR=<path from preload>

Follow strict TDD: write failing test, make it pass, refactor, commit.
Run the full review cycle before each commit: /simplify, /xp-quality-review, /xp-security-triage.

When done, report: what was implemented, which acceptance criteria are met,
commits made, and any concerns or assumptions that need attention.
```

If a sprint is active (SPRINT_FILE provided), include the relevant story ID in the spawn prompt for status tracking.

### Post-Spawn Guidance

After spawning teammates, guide the lead:

1. **Wait** for all teammates to complete (they send completion messages)
2. **Review** each teammate's branch and merge:
   ```
   git merge <worktree-branch> --no-ff
   ```
3. **Resolve** any merge conflicts (file domains should prevent these)
4. **Run** the full test suite on the merged result
5. **Run** `/xp-accept` to verify acceptance criteria

## Recording Events

Record the mode decision:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "xp-assign" \
  --content "Execution mode: <Solo|Worktree subagents> — <rationale>" \
  --topic "execution-mode"
```

For worktree mode, record an assumption per domain boundary:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "assumption" --agent "xp-assign" \
  --content "Domain boundary: <step-A files> independent of <step-B files>"
```
