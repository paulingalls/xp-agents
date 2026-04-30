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

Pick the diff command:
- If `PR_OUTPUT` is a number: `gh pr diff <PR_OUTPUT>`
- Otherwise: `git diff <TARGET_BRANCH>...HEAD`

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nstory\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<chosen diff command>\n\n## Context\nClosing story branch <CURRENT_BRANCH> for story <story-id> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with story-mode focus (AC alignment, file_domain enforcement against sprint.json, story-bounded scope creep, regression risk in unmodified stories). Return Keep / Concern / Block summary."
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

## Step 8: JIT-next dispatch (solo mode)

After the merge, check whether the next in-progress story needs its
branch created on demand. The `next-in-progress` subcommand returns
the lowest-id in-progress story whose deps are all done; cascade-defer
naturally excludes blocked stories.

```bash
NEXT_STORY=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
  --smm-dir <SMM_DIR> next-in-progress) && [ -n "$NEXT_STORY" ]
```

If the command exits non-zero (no eligible next story), **stop the
JIT-next step**. /xp-accept's loop owns the sprint-review dispatch
when the sprint completes; /xp-story-close NEVER fires it itself
(decision e30e9e91e61a — single source of truth lives in /xp-accept).

If `NEXT_STORY` is set, check whether its branch already exists.
Parallel teammate batches set `branch_name` for every parallel-eligible
story at /xp-assign time, so JIT-create is a no-op for teammate mode.
Use `sprint_cli.py get-story-branch` to read the recorded value
(prints the branch name or empty; exit 0 either way):

```bash
NEXT_BRANCH=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
  --smm-dir <SMM_DIR> get-story-branch "$NEXT_STORY")
```

If `NEXT_BRANCH` is **non-empty**, the branch already exists (parallel
teammate batch). Skip JIT-create and stop here — the existing teammate
worktree already drives that story.

If `NEXT_BRANCH` is **empty** (solo mode), JIT-create the branch off
the merged sprint tip and check it out so the orchestrator can begin
the next story:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
  --smm-dir <SMM_DIR> create --cwd . \
  --story "$NEXT_STORY" --slug "<next-story-title-slug>" \
  --base <TARGET_BRANCH>
```

`branching.py create` records `branch_name` in sprint.json
automatically and checks out the new branch. The orchestrator now
sits on the next story's branch with the merged sprint tip as its
base — ready to begin work.

## Reporting Back

Tell the user: story branch merged into sprint, PR (if created)
merged, local branch deleted. If JIT-create ran, name the new branch
and the next story id. /xp-accept's loop continues from here.
