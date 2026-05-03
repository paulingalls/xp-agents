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

Analyze the plan and decide how to execute: solo (sequential) or with CLI teammates (parallel). Stories arrive at /xp-assign in the `scheduled` status (xp-work-selection parks them there). xp-assign promotes scheduled → in-progress as it creates each branch — solo creates only the FIRST scheduled, teammates create ALL.

## Pre-flight

1. If no `PLAN_FILE` — output "No plan file found. Enter plan mode first." Stop.
2. Read the plan at `PLAN_FILE`.
3. If `SPRINT_FILE` provided, read it for story context (optional — status tracking only).
4. Analyze steps for parallelization potential.

## Mode Selection

**Auto-pick solo without prompting** when EITHER:

- only one scheduled story exists (nothing to parallelize), OR
- two or more scheduled stories share at least one file in their `file_domain` (parallel teammates would step on each other).

Use the CLI to decide. The two auto-solo signals are checked separately
for clarity (`scheduled-overlap` exits 0 when overlap exists — i.e.,
"the conflict condition holds" — same convention as `has-active`/
`is-complete`):

```bash
SCHEDULED_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
  --smm-dir ${SMM_DIR} count-status scheduled)

if [ "$SCHEDULED_COUNT" -eq 0 ]; then
  # No scheduled stories — nothing to assign. Return without creating
  # branches. Pre-existing in-progress stories from a prior session
  # stay on their existing branches; xp-assign acts on the new batch
  # only.
  echo "No scheduled stories — nothing to assign. Stop."
  exit 0
elif [ "$SCHEDULED_COUNT" -eq 1 ]; then
  # One scheduled story — nothing to parallelize.
  MODE=solo
elif python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
       --smm-dir ${SMM_DIR} scheduled-overlap; then
  # 2+ scheduled with file_domain overlap — parallel teammates would
  # step on each other.
  MODE=solo
else
  # 2+ scheduled with disjoint file_domains — genuinely parallelizable.
  MODE=$(ask user via AskUserQuestion: "Solo (sequential) or CLI teammates (parallel)?")
fi
```

The predicate intentionally ignores pre-existing in-progress stories
carried over from a prior session — those already have branches and
their own xp-accept lifecycle; xp-assign acts on the new scheduled
batch only.

The plan-driven heuristic still applies: if the plan steps have sequential deps, target overlapping files, or the plan is small (≤3 steps) — favor solo even when not auto-picked. Present the rationale when you ask.

## Branch Creation (Stage 1+)

After mode selection but before execution, transition scheduled stories
to `in-progress` and create their branches — JIT in solo mode, eager in
teammate mode.

1. Read the branching stage:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} stage
```

If stage < 1, skip branch creation entirely.

2. Get the story base branch:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} get-base --cwd .
```

3. **Solo mode** (JIT): promote ONLY the first scheduled story to
`in-progress` and create its branch. The rest stay `scheduled` —
/xp-story-close JIT-promotes the next scheduled story to in-progress
+ creates its branch off the merged sprint tip after each prior story
ships. JIT story branches eliminate the pre-JIT staleness that an
`ff-only` post-step in /xp-accept was trying to patch — the just-
merged-tip base is what the next story needs to build on.

```bash
FIRST_SCHEDULED=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} next-scheduled)

python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} \
  update-story "$FIRST_SCHEDULED" in-progress

git checkout <story-base>

python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  create --cwd . --story "$FIRST_SCHEDULED" \
  --slug <title-slug> --base <story-base>
```

4. **Teammate mode** (eager — parallel-eligible): promote EVERY
scheduled story to `in-progress` and create its branch now, since each
teammate needs its own worktree+branch to spawn into. Per design,
teammates only run parallel work — never chained sequential — so all
scheduled stories at /xp-assign time are parallel-eligible and
unblocked. Each branches off the story base.

```bash
git checkout <story-base>

# For each scheduled story (parallel batch):
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} \
  update-story <story-id> in-progress
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  create --cwd . --story <story-id> --slug <title-slug> --base <story-base>
```

The `create` command auto-records `branch_name` in sprint.json.

**Teammate-mode only:** after creating all parallel branches, return
to the story base so subsequent teammate spawns have a clean starting
point. Solo mode skips this — it stays on the single branch it just
created (the next section's "Solo Mode" hands off from there for the
JIT-first-story workflow).

```bash
# teammate mode only:
git checkout <story-base>
```

## Solo Mode

Solo mode uses file-domain matching at commit time — no story assignment needed. The commit hook resolves story attribution by matching committed files against each in-progress story's `file_domain`.

Checkout the first in-progress story's branch (the one just promoted from `scheduled` above):
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
4. Run `/xp-accept` to verify acceptance criteria for each in-progress story

The orchestrator does NOT merge teammate branches. Each story branch
stays alive on its teammate worktree until its `/xp-story-close`
invocation merges it (dispatched by `/xp-accept` per accepted story).
This mirrors solo mode timing: per-story merge belongs to
`/xp-story-close`, not `/xp-assign`.

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
