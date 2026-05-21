---
name: xp-story-close
description: >-
  Per-story close: review the story diff, merge into the sprint base,
  and (solo mode) JIT-create the next scheduled story's branch off
  the merged tip. Invoked by /xp-accept on each accepted story; the
  sprint-review dispatch is owned by /xp-accept after its loop
  completes — single source of truth lives there.
allowed-tools:
  - Read
  - Write
  - Bash
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */scripts/branching.py *)
  - Bash(python3 */scripts/close_common.py *)
  - Bash(python3 */smm/sprint_cli.py *)
  - Bash(python3 */scripts/cleanup_teammate.py *)
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Story Close

The preload above surfaces `SMM_DIR`, `TEAMMATE_CWD`, `CURRENT_BRANCH`,
`TARGET_BRANCH`, `GH_AVAILABLE`, `WORKTREE_CLEAN`. `TARGET_BRANCH` is
the merge destination — the sprint branch at stage 2+, primary
otherwise. Shared pipeline lives in
`${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

`TEAMMATE_CWD` is non-empty when closing a teammate story (orchestrator
sits on the sprint branch; teammate commits live in
`.claude/worktrees/worktree-<story-id>`). Requires the story in
`closing` state (set by `/xp-accept` Step 1.5) — the worktree lookup
keys on it. Steps 1, 2, 3 route `close_common.py` at
`--cwd ${TEAMMATE_CWD:-.}`. Step 7 (merge) ALWAYS runs at orchestrator
cwd (`--cwd .`) — `git merge` checks out the target branch held by the
orchestrator's worktree, so running it from the teammate cwd fails with
`'<target>' is already used by worktree`. Step 7b also runs at
orchestrator cwd (`git worktree` operates on the parent registry).
Solo flow: every step uses orchestrator cwd.

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd ${TEAMMATE_CWD:-.} --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

Stop on non-zero exit; the script emitted the reason on stderr.

## Step 1b: Validate file_domain

Surface file_domain drift to stderr before the reviewer fork. Default
`XP_FILE_DOMAIN_DRIFT_TOLERANCE=1` absorbs a single drifting file
(set `0` for strict). Do NOT emit a concern event — per convention,
drift is a planning signal that retro surfaces from `cascade_size`;
emitting per-close concerns pollutes the open-event surface. Continue
regardless of drift state.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  validate-domain <story-id> --base <TARGET_BRANCH> \
  --cwd ${TEAMMATE_CWD:-.} >/dev/null || true
```

## Step 1c: Verify-touch gate

Read the preload's `VERIFY_UNTOUCHED` and `VERIFY_DEFERRED`.

If `VERIFY_UNTOUCHED` is non-empty AND `VERIFY_DEFERRED` is `false`,
**refuse the close**: tell the user `no commit touched <VERIFY_UNTOUCHED>`
and stop here — do NOT push, create a PR, or merge. The story branch
needs a commit that touches each declared acceptance-test path, or a
`[verify-deferred] <reason>` commit to defer it (the deferral is
recorded as debt). The customer can re-run `/xp-accept` after adding
the touching (or deferring) commit.

If `VERIFY_DEFERRED` is `true`, the deferral is on record — proceed.
If `VERIFY_UNTOUCHED` is empty, the gate passes — proceed.

## Step 2: Push the story branch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py push \
  --cwd ${TEAMMATE_CWD:-.} --branch <CURRENT_BRANCH>
```

Stdout is `pushed: <branch>` or `skipped: no remote configured`.

## Step 3: PR creation

```bash
PR_OUTPUT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py create-pr \
  --cwd ${TEAMMATE_CWD:-.} --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "[<story-id>] <story title>" --body "<story summary + AC bullets>")
```

`PR_OUTPUT` is a PR number or `skipped: no gh on PATH`.

## Step 4: Security Review (skipped)

Skipped — sprint-close runs cumulative `/security-review` for all merged stories.

## Step 4.5: Fork the close-reviewer

Compute the diff command:

```bash
DIFF_CMD=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py diff-command \
  --pr-output "$PR_OUTPUT" --target <TARGET_BRANCH>)
```

Substitute the captured value as `<DIFF_CMD>` in the agent prompt below.

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\nSYSTEM_CONTEXT_RENDERED=<SYSTEM_CONTEXT_RENDERED>\n\n## Mode\nstory\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Close Cycle ID\n<CLOSE_CYCLE_ID>\n\n## Context\nClosing story branch <CURRENT_BRANCH> for story <story-id> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with story-mode focus (AC alignment, file_domain enforcement against sprint.json, story-bounded scope creep, regression risk in unmodified stories). Return Keep / Concern / Block summary."
)
```

## Steps 5–6: Apply shared close-pipeline reference

The shared close-pipeline reference (Steps 5, 5b, 6) is emitted by the
preload — see `scripts/_close_pipeline_shared.md`. Apply in order after
Step 4.5, then continue with Step 7.

**Story-close override for Step 6 (auto-merge gate):** skip the shared
Step 6 `AskUserQuestion` and proceed to Step 7 when ALL hold:

1. Step 5c queued zero ask-user items, verified via:
   ```bash
   ASK_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
     --smm-dir <SMM_DIR> count-classifications \
     --route ask --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
   ```
   `<CLOSE_CYCLE_ID>` and `<CLOSE_START_TS>` come from the preload.
   `--cycle-id` scopes by close-cycle (SMM is shared across worktrees).
   Test `[ "$ASK_COUNT" -gt 0 ]` → fall through to shared Step 6.
2. No Block-severity finding in Step 4.5's reviewer summary.
3. Preload emitted a non-empty `TEST_COMMAND=...` AND running it after
   all Step 5c fixes landed exits 0.

When `TEST_COMMAND` is empty, print this hint before falling through:

```
Auto-merge disabled — set stack.test_command in system_context.json to enable.
To set it, pipe the command (JSON-quoted) into the edit-stack-field CLI:
    printf %s '"<your-test-command>"' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> edit-stack-field test_command
```

When all three conditions hold, print:
"All reviewer findings addressed and tests green — proceeding to merge
without confirmation."
then continue to Step 7. Otherwise apply the shared Step 6 prompt.

## Step 7: Merge

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

Always at orchestrator cwd (see intro). Any failing step aborts the
chain — source intact for retry. Conflicts are never auto-resolved.

## Step 7b: Teammate worktree cleanup (if applicable)

If the just-closed story was a teammate's, a worktree exists at
`.claude/worktrees/worktree-<story-id>`. Solo stories have no worktree
to clean up.

```bash
STORY_ID=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
  --smm-dir <SMM_DIR> extract-story-id --branch "<CURRENT_BRANCH>")
WORKTREE_NAME=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
  --smm-dir <SMM_DIR> find-teammate-worktree \
  --story-id "$STORY_ID" --cwd .)

if [ -n "$WORKTREE_NAME" ]; then
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup_teammate.py \
    --name "$WORKTREE_NAME" --smm-dir <SMM_DIR>
fi
```

## Step 8: JIT-next dispatch (solo mode)

After the merge, dispatch the next story. Two states:

- **An in-progress story remains** (parallel-teammate batch from
  /xp-assign — branches already exist). Skip JIT-create.
- **No in-progress, but scheduled stories queued** (solo mode normal
  case). Promote the next scheduled story to in-progress and JIT-create
  its branch off the merged tip.

Pass `--treat-as-done "$STORY_ID"` so the dep gate counts the
just-closed story as satisfied (its on-disk status is still `closing`
until /xp-accept Step 4 marks done after this dispatch returns).

```bash
if NEXT_STORY=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir <SMM_DIR> next-in-progress \
    --treat-as-done "$STORY_ID"); then
  NEXT_BRANCH=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir <SMM_DIR> get-story-branch "$NEXT_STORY")
  if [ -z "$NEXT_BRANCH" ]; then
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
      --smm-dir <SMM_DIR> create --cwd . \
      --story "$NEXT_STORY" --slug "<next-story-title-slug>" \
      --base <TARGET_BRANCH>
  fi
elif NEXT_STORY=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir <SMM_DIR> next-scheduled \
    --treat-as-done "$STORY_ID"); then
  python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir <SMM_DIR> update-story "$NEXT_STORY" in-progress
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
    --smm-dir <SMM_DIR> create --cwd . \
    --story "$NEXT_STORY" --slug "<next-story-title-slug>" \
    --base <TARGET_BRANCH>
fi
# Else: no in-progress AND no scheduled — sprint complete; the
# sprint-review dispatch is /xp-accept's responsibility.
```

`branching.py create` records `branch_name` in sprint.json and checks
out the new branch.

## Reporting Back

Tell the user: story branch merged into sprint, PR (if created)
merged, local branch deleted. If JIT-create ran, name the new branch
and the next story id. /xp-accept's loop continues from here.
