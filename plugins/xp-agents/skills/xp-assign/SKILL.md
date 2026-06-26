---
name: xp-assign
description: >-
  Split a reviewed teammate-mode plan per teammate, create their branches, and
  spawn parallel CLI teammates. Runs after /xp-schedule promotes the teammate
  batch and the plan is reviewed. Parallel execution only — solo is /xp-schedule.
allowed-tools:
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(*/scripts/spawn_teammate.py *)
  - Bash(python3 */scripts/branching.py *)
  - Bash(git checkout *)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Work Assignment

> **Sequential discipline.** The harness batches independent tool calls in
> parallel; this skill is step-gated. Run Pre-flight → Branch Creation →
> CLI-Teammate strictly, one step per turn — make the call, observe, then decide
> the next. Never spawn the same subagent twice; spawning all teammates in one
> block is the deliberate exception (independent, by design). Independent
> read-only calls may still batch.

Split a reviewed **teammate-mode** plan and spawn parallel teammates. The
decide-half (solo vs parallel, promotion, solo branch) belongs to `/xp-schedule`:
by the time xp-assign runs, `/xp-schedule` has already promoted the batch to
`in-progress` with `execution_mode=teammate`, and the preload lists them as
`TEAMMATE_STORY_IDS`. xp-assign only splits the reviewed plan per teammate,
creates their branches, and spawns them.

## Pre-flight

1. If no `PLAN_FILE` — output "No plan file found. Enter plan mode first." Stop.
2. Read the plan at `PLAN_FILE`.
3. If `SPRINT_FILE` provided, read it for story context (optional — status tracking only).
4. If `TEAMMATE_STORY_IDS` is empty, there is no teammate batch to assign — stop
   (a solo frontier never reaches xp-assign; `/xp-schedule` branched it directly).
5. Analyze the plan to split work per teammate story.

## Branch Creation (Stage 1+)

Create one branch per teammate story. `/xp-schedule` already promoted the batch to
`in-progress` with `execution_mode=teammate`; xp-assign only creates the branches
each teammate worktree spawns into. If stage < 1, skip branch creation entirely.

```bash
BASE=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} get-base --cwd .)
git checkout "$BASE"

for sid in $TEAMMATE_STORY_IDS; do
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
    create --cwd . --story "$sid" --slug <title-slug> --base "$BASE"
done

# Return to the story base so each teammate spawns from a clean starting point.
git checkout "$BASE"
```

## CLI Teammate Mode

### 1. Write Prompt Files

Write a self-contained prompt per teammate story (one per `TEAMMATE_STORY_IDS`
entry) to `/tmp/prompt-step-N.txt`. The teammate has no prior context. Include:

- **Milestone Context** — design_details and constraints from execution_plan.json
- **Story Context** — what THIS story uniquely does (don't restate milestone rationale)
- **File Domain** — files this step exclusively owns
- **What to Change** — detailed changes from plan
- **Acceptance Criteria** — derived from plan goals
- **Interface Contracts** — shared boundaries with other steps
- **Story Branch** — the branch name created for this story (from sprint.json `branch_name`)
- **SMM Directory** — `SMM_DIR=<path>`
- TDD + review cycle instructions

### 2. Spawn Teammates

Launch each via Bash with `run_in_background`, passing `--story-id story-NNN`,
`--branch <story-branch>`, and `--plugin-dir ${CLAUDE_PLUGIN_ROOT}`. The
`--plugin-dir` is **required**: a headless `claude -p` worktree session does not
apply the project-scoped marketplace enablement, so without it the teammate
loads none of the xp-agents skills, agents, or hooks (no TDD/review/commit gates,
no SMM event recording). `${CLAUDE_PLUGIN_ROOT}` resolves to the lead's live
plugin dir, so the teammate runs the same plugin version as the lead.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py --name worktree-story-NNN \
  --smm-dir ${SMM_DIR} --prompt-file /tmp/prompt-step-N.txt \
  --story-id story-NNN --branch <story-branch> \
  --plugin-dir ${CLAUDE_PLUGIN_ROOT} 2>&1 \
  | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_output_filter.py \
  --smm-dir ${SMM_DIR} --teammate-id worktree-story-NNN
```

Spawn all teammates in parallel (multiple Bash calls in one message).

### 3. Post-Spawn

1. Wait for Bash task notifications
2. Read task output for branch name, report path, cost
3. Read report file for summary
4. Run `/xp-accept` to verify acceptance criteria for each in-progress story

The orchestrator does NOT merge teammate branches. Each story branch stays alive
on its teammate worktree until its `/xp-story-close` invocation merges it
(dispatched by `/xp-accept` per accepted story).
