---
name: xp-assign
description: >-
  Analyze sprint stories, decide execution mode (solo vs worktree subagents),
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

Analyze the sprint and decide how to execute: solo (sequential) or with worktree-isolated subagents (parallel).

## Pre-flight Checks

1. If `SPRINT_FILE` was not provided — output: "No sprint data. Run `/xp-sprint-start` first." Stop.
2. Read the sprint file at `SPRINT_FILE` path.
3. If all stories have status `done` or `deferred` — output: "All stories complete." Stop.
4. Count stories with status `ready` or `in-progress`.
5. If only 1 active story — output: "Single story — proceeding solo." Stop (solo is implicit).

## Mode Selection

Evaluate the active stories and choose a mode:

**Solo** (sequential execution by the lead) when ANY of these apply:
- All active stories have dependency chains between them
- All active stories are size S
- Story file domains overlap (shared files between stories)
- File domains are missing from stories (can't verify independence)

**Worktree subagents** (parallel execution) when ALL of these apply:
- 2+ active stories with no dependencies between them
- Stories are size M or L (worth the coordination overhead)
- Stories have non-overlapping file domains

Present the recommendation to the user via `AskUserQuestion`:
- **Mode** (Solo or Worktree Subagents) with rationale
- For worktree mode: which stories run in parallel, which are sequential

## Solo Mode

If solo: output "Proceeding with solo execution." and stop. The lead continues working on stories sequentially — no additional orchestration needed.

## Worktree Subagent Mode

For each parallel story, spawn an `xp-teammate` agent:

```
Agent({
  description: "Story NNN: <title>",
  subagent_type: "xp-teammate",
  isolation: "worktree",
  run_in_background: true,
  prompt: "<spawn prompt below>"
})
```

### Spawn Prompt Template

Each spawn prompt must be self-contained — the teammate has no context beyond what you provide:

```
You are implementing story-NNN: <title>

## Context
<inlined design context from the story>

## File Domain
<list of files this story exclusively owns>

## Acceptance Criteria
<list from the story>

## Interface Contracts
<shared boundaries with other stories, if any>

## SMM Directory
SMM_DIR=<path from preload>

Follow strict TDD: write failing test, make it pass, refactor, commit.
Run the full review cycle before each commit: /simplify, /xp-quality-review, /xp-security-triage.

When done, report: what was implemented, which acceptance criteria are met,
commits made, and any concerns or assumptions that need attention.
```

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
  --content "Domain boundary: <story-A files> independent of <story-B files>"
```
