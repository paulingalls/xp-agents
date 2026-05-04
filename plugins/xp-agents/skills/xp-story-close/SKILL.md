---
name: xp-story-close
description: >-
  Per-story close: review the story diff, merge into the sprint base,
  and (solo mode) JIT-create the next in-progress story's branch off
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
`TARGET_BRANCH`, `GH_AVAILABLE`, and `WORKTREE_CLEAN`. Use these values
verbatim — do not recompute them. `TARGET_BRANCH` is the story base
(sprint branch at stage 2+, primary otherwise) — the merge destination
for the just-completed story. The shared close pipeline lives in
`${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

`TEAMMATE_CWD` is set when /xp-accept dispatched /xp-story-close for a
teammate story (the orchestrator sits on the sprint branch; the
teammate's commits live in `.claude/worktrees/worktree-<story-id>`).
When non-empty, Steps 1, 2, and 3 route `close_common.py` at the
teammate's worktree via `--cwd ${TEAMMATE_CWD:-.}` (preflight, push,
PR creation — operations local to the teammate's branch). Step 7
(merge) ALWAYS runs at the orchestrator cwd (`--cwd .`) because
`git merge` checks out the target branch, and the target is already
held by the orchestrator's worktree — running merge at the teammate's
cwd would fail with `'<target>' is already used by worktree at '<orch>'`.
Step 7b's worktree cleanup also always runs at the orchestrator cwd
because `git worktree list/remove` operate on the parent repo's
worktree registry. When TEAMMATE_CWD is empty (solo flow), every
step operates on the orchestrator's cwd as today.

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd ${TEAMMATE_CWD:-.} --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

If the exit code is non-zero, **stop**. The script emitted the reason
on stderr (dirty worktree or `<CURRENT_BRANCH>` IS `<TARGET_BRANCH>`).

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

## Step 4: Fork the close-reviewer

Compute the diff command:

```bash
DIFF_CMD=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py diff-command \
  --pr-output "$PR_OUTPUT" --target <TARGET_BRANCH>)
```

Substitute the captured value as `<DIFF_CMD>` in the agent prompt below.

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nstory\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Close Cycle ID\n<CLOSE_CYCLE_ID>\n\n## Context\nClosing story branch <CURRENT_BRANCH> for story <story-id> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with story-mode focus (AC alignment, file_domain enforcement against sprint.json, story-bounded scope creep, regression risk in unmodified stories). Return Keep / Concern / Block summary."
)
```

## Step 4.5: Conditional Security Review

Story-close normally relies on sprint-close's cumulative
`/security-review` to cover each merged story. That assumption fails
when **no sprint envelope wraps this close** — either (a) no sprint
exists at all, or (b) `<CURRENT_BRANCH>` is an orphan story branch
(not referenced by any active `ready` / `in-progress` / `reviewing`
story in `sprint.json`). Without the conditional below, the
cumulative `/security-review` would never fire for the story's diff
and only commit-time deterministic scans would cover it.

Determine whether Step 4.5 applies:

```bash
if ! python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
       --smm-dir <SMM_DIR> exists; then
  STEP_4_5_APPLIES=1   # sprint_exists() is false — no sprint at all
elif python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
       --smm-dir <SMM_DIR> list-story-orphans \
       --cwd ${TEAMMATE_CWD:-.} \
     | grep -qx "<CURRENT_BRANCH>"; then
  STEP_4_5_APPLIES=1   # orphan story branch — no active sprint story owns it
else
  STEP_4_5_APPLIES=0   # sprint envelope wraps this story — sprint-close covers it
fi
```

When `STEP_4_5_APPLIES=1`, apply the shared `### Step 4.5: Security
Review` block above with `<close-mode>` → `story` and
`<close-skill-name>` → `xp-story-close`. Step 4.5 concerns recorded
here flow into the shared Step 6 abort-default count exactly the
same way they do for free/sprint/plan close.

When `STEP_4_5_APPLIES=0`, skip Step 4.5 — sprint-close's cumulative
diff already covers each story.

## Steps 5–6: Apply shared close-pipeline reference

The shared close-pipeline reference (Steps 5, 5b, and 6) is emitted by
the preload at the top of this context — see
`scripts/_close_pipeline_shared.md` for the source. Apply those three
steps in order after Step 4.5, then continue with Step 7 below.

**Story-close override for Step 6 (auto-merge gate):** if ALL of these
hold, skip the shared Step 6's `AskUserQuestion` and proceed directly
to Step 7:
1. Step 5c queued zero ask-user items. Verify deterministically via
   the canonical structured filter:
   ```bash
   ASK_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
     --smm-dir <SMM_DIR> count-classifications \
     --route ask --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
   ```
   `<CLOSE_CYCLE_ID>` and `<CLOSE_START_TS>` are emitted by the preload
   above (captured at close-cycle start). `--cycle-id` is the strict
   scoper — it prevents concurrent close-cycles in other teammate
   worktrees from leaking concern_classify events into this count
   (SMM is shared across worktrees). `--since-ts` is belt-and-
   suspenders defense for the same-worktree resume case. The CLI
   filters on `metadata.action == "concern_classify"` +
   `metadata.route == "ask"` + `metadata.close_cycle_id == CLOSE_CYCLE_ID`
   + `ts >= CLOSE_START_TS` — structured fields, not regex. Test
   numerically: `[ "$ASK_COUNT" -gt 0 ]` → fall through to the shared
   Step 6 prompt.
2. No Block-severity finding survived in Step 4's reviewer summary.
3. The preload above emitted a non-empty `TEST_COMMAND=...` line
   (sourced from `system_context.stack.test_command`) AND running
   that command AFTER all Step 5c fixes landed exits 0. Any non-zero
   exit means tests aren't green — fall through to the shared Step 6
   prompt.

When `TEST_COMMAND` is empty (the project hasn't configured a test
command), the gate cannot fire. Print this two-line discovery hint
before falling through to the shared Step 6 prompt:

```
Auto-merge disabled — set stack.test_command in system_context.json to enable.
To set it, pipe the command (JSON-quoted) into the edit-stack-field CLI:
    printf %s '"<your-test-command>"' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> edit-stack-field test_command
```

Substitute `<your-test-command>` with the project's test runner
invocation. The `printf %s` form avoids shell-quoting traps when the
command itself contains spaces or special characters.

When all three conditions hold, print exactly:
"All reviewer findings addressed and tests green — proceeding to merge
without confirmation."
then continue to Step 7. Otherwise apply the shared Step 6
`AskUserQuestion` as written. The deterministic green-tests gate
matches the auto-accept pattern in `/xp-accept`; LLM judgment from
Step 5c alone is not sufficient to skip user confirmation.

## Step 7: Merge

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

Merge ALWAYS runs at the orchestrator cwd (`--cwd .`), even for
teammate stories. `git merge` checks out the target branch; if the
orchestrator already holds it (sprint branch), checkout from the
teammate's worktree fails (`'<target>' is already used by worktree`).

The script chains: merge `--no-ff` → push target (if remote) → delete
source. Any step failing aborts the chain — the source branch always
survives a failed step so the user can resolve and retry.

## Step 7b: Teammate worktree cleanup (if applicable)

If the story being closed was a teammate's, a worktree exists at
`.claude/worktrees/worktree-<story-id>`. Solo stories have no
worktree to clean up. Per-story symmetry puts the cleanup here, not
bulk-after-loop in /xp-accept.

Use `branching.py` subcommands to derive story id from the
just-closed `<CURRENT_BRANCH>` and locate the matching live teammate
worktree. Both subcommands print empty stdout + exit 0 when there's
no match (story-id from a non-story branch, or no live teammate for
this story), so an `if [ -n ... ]` shell guard handles solo mode
without special-casing:

```bash
STORY_ID=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
  --smm-dir <SMM_DIR> extract-story-id --branch "<CURRENT_BRANCH>")
WORKTREE_NAME=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
  --smm-dir <SMM_DIR> find-teammate-worktree \
  --story-id "$STORY_ID" --cwd .)
```

`extract-story-id` parses `<user>/story-NNN[-<slug>]` (lives in
`identity.py::extract_story_id`); `find-teammate-worktree` walks
`git worktree list --porcelain` and matches the exact
`worktree-<story-id>` directory name (lives in
`worktree.py::find_teammate_worktree_for_story`, mirrors
`has_live_teammates`'s real-git-state pattern).

Run cleanup ONLY when `WORKTREE_NAME` is non-empty:

```bash
if [ -n "$WORKTREE_NAME" ]; then
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup_teammate.py \
    --name "$WORKTREE_NAME" --smm-dir <SMM_DIR>
fi
```

`cleanup_teammate.py` verifies the branch is merged before removing
the worktree, branch, markers, and report. The merge in Step 7
already ran, so the merge check passes.

## Step 8: JIT-next dispatch (solo mode)

After the merge, find the next story to work and (in solo mode) create
its branch on demand. Two states to handle:

- **Another in-progress story remains** — the parallel-teammate batch at
  /xp-assign promoted them all; their branches already exist.
  /xp-story-close has nothing to create.
- **No in-progress remains, but scheduled stories are queued** — solo
  mode's normal case under the four-state lifecycle. The next scheduled
  story is promoted to in-progress here and its branch is created off
  the just-merged sprint tip, so chained branches are never stale.

Wrap each path in an explicit shell guard. If both subcommands exit
non-zero (no in-progress AND no scheduled), the sprint is complete —
/xp-accept's loop owns the sprint-review dispatch (single source of
truth lives in /xp-accept).

```bash
if NEXT_STORY=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir <SMM_DIR> next-in-progress); then
  # Parallel-teammate batch: branch was eagerly created at /xp-assign
  # and is already named in sprint.json. Skip JIT-create unless empty
  # (defensive — solo would have created at /xp-assign too).
  NEXT_BRANCH=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir <SMM_DIR> get-story-branch "$NEXT_STORY")
  if [ -z "$NEXT_BRANCH" ]; then
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
      --smm-dir <SMM_DIR> create --cwd . \
      --story "$NEXT_STORY" --slug "<next-story-title-slug>" \
      --base <TARGET_BRANCH>
  fi
elif NEXT_STORY=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir <SMM_DIR> next-scheduled); then
  # Solo-mode fallback: promote the next scheduled story to
  # in-progress, then JIT-create its branch off the merged sprint tip.
  python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir <SMM_DIR> update-story "$NEXT_STORY" in-progress
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
    --smm-dir <SMM_DIR> create --cwd . \
    --story "$NEXT_STORY" --slug "<next-story-title-slug>" \
    --base <TARGET_BRANCH>
fi
# Else: no in-progress AND no scheduled — sprint complete, the
# sprint-review dispatch is /xp-accept's responsibility (decision
# e30e9e91e61a — single source of truth lives there).
```

`sprint_cli.py next-in-progress` and `next-scheduled` both return the
lowest-id story with the named status whose deps are ALL done; cascade-
defer naturally excludes blocked stories. Both exit non-zero when no
match exists, so the explicit `if/elif` chain reads naturally.

`branching.py create` records `branch_name` in sprint.json
automatically and checks out the new branch. The orchestrator now
sits on the next story's branch with the merged sprint tip as its
base — ready to begin work.

## Reporting Back

Tell the user: story branch merged into sprint, PR (if created)
merged, local branch deleted. If JIT-create ran, name the new branch
and the next story id. /xp-accept's loop continues from here.
