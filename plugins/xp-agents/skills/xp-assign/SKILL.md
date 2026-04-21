---
name: xp-assign
description: >-
  Analyze plan steps, decide execution mode (solo vs CLI teammates),
  and either proceed solo or spawn teammates for parallel execution.
  Auto-run after planning completes.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(*/scripts/spawn_teammate.py *)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Work Assignment

Analyze the plan and decide how to execute: solo (sequential) or with CLI teammates (parallel).

## Pre-flight

1. If no `PLAN_FILE` — output "No plan file found. Enter plan mode first." Stop.
2. Read the plan at `PLAN_FILE`.
3. If `SPRINT_FILE` provided, read it for story context (optional — status tracking only).
4. Analyze steps for parallelization potential.

## Mode Selection

**Solo** when ANY apply: steps have sequential deps, steps target overlapping files, plan is small (≤3 steps).

**CLI teammates** when ALL apply: 2+ independent step groups with no deps, non-overlapping files, steps substantial enough to justify coordination.

Present recommendation via `AskUserQuestion`: mode + rationale. For teammate mode: which groups run in parallel.

## Solo Mode

If a sprint is active with in-progress stories, assign the most relevant story for commit attribution:

```bash
python3 ${PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> assign-story story-NNN --name main
```

Output "Proceeding with solo execution." and stop.

## CLI Teammate Mode

### 1. Write Prompt Files

Write a self-contained prompt per step group to `/tmp/prompt-step-N.txt`. The teammate has no prior context. Include these sections:

- **Milestone Context** — design_details and constraints from execution_plan.json
- **Story Context** — what THIS story uniquely does (don't restate milestone rationale)
- **File Domain** — files this step exclusively owns
- **What to Change** — detailed changes from plan
- **Acceptance Criteria** — derived from plan goals
- **Interface Contracts** — shared boundaries with other steps
- **SMM Directory** — `SMM_DIR=<path>`
- TDD + review cycle instructions

If sprint active, include story ID for status tracking.

### 2. Spawn Teammates

Launch each via Bash with `run_in_background`. Pass `--story-id story-NNN` when sprint is active (writes `.story-assignment-{name}` marker for commit attribution):

```bash
python3 ${PLUGIN_ROOT}/scripts/spawn_teammate.py --name teammate-step-N \
  --smm-dir ${SMM_DIR} --prompt-file /tmp/prompt-step-N.txt \
  --story-id story-NNN 2>&1 \
  | python3 ${PLUGIN_ROOT}/scripts/teammate_output_filter.py \
  --smm-dir ${SMM_DIR} --teammate-id teammate-step-N
```

Spawn all teammates in parallel (multiple Bash calls in one message).

### 3. Post-Spawn

1. Wait for Bash task notifications
2. Read task output for branch name, report path, cost
3. Read report file for summary
4. Merge: `git merge teammate-step-N --no-ff`
5. Run full test suite on merged result
6. Run `/xp-accept` to verify acceptance criteria

## Recording Events

Record the mode decision and domain boundaries:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "xp-assign" \
  --content "Execution mode: <Solo|CLI teammates> — <rationale>" \
  --topic "execution-mode"

# For teammate mode, one per domain boundary:
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "assumption" --agent "xp-assign" \
  --content "Domain boundary: <step-A files> independent of <step-B files>"
```
