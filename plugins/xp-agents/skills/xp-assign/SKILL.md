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
  - Bash(python3 */scripts/branching.py *)
  - Bash(git checkout *)
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

## Branch Creation (Stage 1+)

After mode selection but before execution, create story branches —
JIT in solo mode, eager in teammate mode.

1. Read the branching stage:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} stage
```

If stage < 1, skip branch creation entirely.

2. Get the story base branch:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} get-base --cwd .
```

3. **Solo mode** (JIT): create ONLY the first in-progress story's branch.
Subsequent in-progress stories get their branches at /xp-story-close
time, born off the merged sprint tip — so chained branches are never
stale (decision df47c932fbe6 — JIT story branches eliminate the
pre-JIT staleness that an `ff-only` post-step in /xp-accept was
trying to patch). The just-merged-tip base is what the next story
needs to build on.

```bash
git checkout <story-base>

python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  create --cwd . --story <first-in-progress-story-id> \
  --slug <title-slug> --base <story-base>
```

4. **Teammate mode** (eager — parallel-eligible): create branches for
EVERY in-progress story now, since each teammate needs its own
worktree+branch to spawn into. Per design, teammates only run parallel
work — never chained sequential — so all in-progress stories at
/xp-assign time are parallel-eligible and unblocked. Each branches
off the story base.

```bash
git checkout <story-base>

# For each in-progress story (parallel batch):
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  create --cwd . --story <story-id> --slug <title-slug> --base <story-base>
```

The `create` command auto-records `branch_name` in sprint.json. After
creating all branches, return to the story base for mode execution:

```bash
git checkout <story-base>
```

## Solo Mode

Solo mode uses file-domain matching at commit time — no story assignment needed. The commit hook resolves story attribution by matching committed files against each in-progress story's `file_domain`.

Checkout the first in-progress story's branch:
```bash
git checkout <first-story-branch>
```

Output "Proceeding with solo execution on `<first-story-branch>`." and stop.

## CLI Teammate Mode

### 1. Write Prompt Files

Write a self-contained prompt per step group to `/tmp/prompt-step-N.txt`. The teammate has no prior context. Include these sections:

- **Milestone Context** — design_details and constraints from execution_plan.json
- **Story Context** — what THIS story uniquely does (don't restate milestone rationale)
- **File Domain** — files this step exclusively owns
- **What to Change** — detailed changes from plan
- **Acceptance Criteria** — derived from plan goals
- **Interface Contracts** — shared boundaries with other steps
- **Story Branch** — the branch name created for this story (from sprint.json `branch_name`)
- **SMM Directory** — `SMM_DIR=<path>`
- TDD + review cycle instructions

If sprint active, include story ID for status tracking.

### 2. Spawn Teammates

Launch each via Bash with `run_in_background`. Pass `--story-id story-NNN` and `--branch <story-branch>` when sprint is active:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py --name worktree-story-NNN \
  --smm-dir ${SMM_DIR} --prompt-file /tmp/prompt-step-N.txt \
  --story-id story-NNN --branch <story-branch> 2>&1 \
  | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_output_filter.py \
  --smm-dir ${SMM_DIR} --teammate-id worktree-story-NNN
```

Spawn all teammates in parallel (multiple Bash calls in one message).

### 3. Post-Spawn

1. Wait for Bash task notifications
2. Read task output for branch name, report path, cost
3. Read report file for summary
4. Merge each teammate's story branch: `git merge <story-branch> --no-ff`
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
