---
name: xp-story-close
description: >-
  Per-story close: review the story diff, merge into the sprint base,
  and (solo mode) JIT-create the next in-progress story's branch off
  the merged tip. Invoked by /xp-accept on each accepted story; the
  sprint-review dispatch is /xp-accept's responsibility after its
  loop completes (decision e30e9e91e61a — single source of truth).
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

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. Use these values verbatim — do
not recompute them. `TARGET_BRANCH` is the story base (sprint branch
at stage 2+, primary otherwise) — the merge destination for the
just-completed story. The shared close pipeline lives in
`${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd . --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

If the exit code is non-zero, **stop**. The script emitted the reason
on stderr (dirty worktree or `<CURRENT_BRANCH>` IS `<TARGET_BRANCH>`).

## Step 2: Push the story branch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py push \
  --cwd . --branch <CURRENT_BRANCH>
```

Stdout is `pushed: <branch>` or `skipped: no remote configured`.

## Step 3: PR creation

```bash
PR_OUTPUT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py create-pr \
  --cwd . --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
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
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nstory\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Context\nClosing story branch <CURRENT_BRANCH> for story <story-id> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with story-mode focus (AC alignment, file_domain enforcement against sprint.json, story-bounded scope creep, regression risk in unmodified stories). Return Keep / Concern / Block summary."
)
```

## Step 5: Present findings

Output the reviewer's Keep / Concern / Block summary verbatim to the
user. The tool result is not visible to them — surface it as text.

## Step 5b: Resolve Addressed Concerns

Per recorded auto-resolve-per-mode policy (story+sprint YES, plan+free
NO), scan for open concerns this story's commits likely addressed:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/triage_preload.py \
  --smm-dir <SMM_DIR>
```

Focus on the "Open Concerns" section. For each concern annotated with
**LIKELY ADDRESSED**: use your session context and the listed commits
to judge whether the concern was genuinely fixed. When confident,
auto-resolve:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py \
  triage-drop --smm-dir <SMM_DIR> --event-id <event-id>
```

When in doubt, leave open — it surfaces at the next kickoff for
manual triage. Report how many were auto-resolved alongside the
reviewer findings before asking the user to confirm the merge.

## Step 6: Confirm the merge

Use `AskUserQuestion` to ask whether to proceed with the merge. Two
options: "Merge into ${TARGET_BRANCH}" or "Abort — fix concerns first".

If the user picks abort, stop here. The branch and PR (if any) stay
intact for follow-up work.

## Step 7: Merge

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

The script chains: merge `--no-ff` → push target (if remote) → delete
source. Any step failing aborts the chain — the source branch always
survives a failed step so the user can resolve and retry.

## Step 7b: Teammate worktree cleanup (if applicable)

If the story being closed was a teammate's, a worktree exists at
`.claude/worktrees/worktree-<story-id>`. Solo stories have no
worktree to clean up. Per-story symmetry (decision 9029c07ae198)
puts the cleanup here, not bulk-after-loop in /xp-accept.

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
/xp-accept's loop owns the sprint-review dispatch (decision
e30e9e91e61a — single source of truth lives in /xp-accept).

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
