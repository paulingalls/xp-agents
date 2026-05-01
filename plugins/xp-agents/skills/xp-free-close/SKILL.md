---
name: xp-free-close
description: >-
  Push the current free branch, fork xp-close-reviewer for free-mode
  review, and merge into the primary integration branch with cleanup.
  Used for ad-hoc work performed outside a sprint or plan; degrades
  gracefully when gh is unavailable.
allowed-tools:
  - Read
  - Write
  - Bash
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */scripts/branching.py *)
  - Bash(python3 */scripts/close_common.py *)
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Free Close

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. Use these values verbatim — do
not recompute them. `TARGET_BRANCH` is the primary integration branch
(free-close merges a free branch → primary). The shared close pipeline
lives in `${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd . --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

If the exit code is non-zero, **stop**. The script emitted the reason
on stderr (dirty worktree or `<CURRENT_BRANCH>` IS `<TARGET_BRANCH>`).

## Step 2: Push the free branch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py push \
  --cwd . --branch <CURRENT_BRANCH>
```

Stdout is `pushed: <branch>` or `skipped: no remote configured`.

## Step 3: PR creation

```bash
PR_OUTPUT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py create-pr \
  --cwd . --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "<short title for the free work>" --body "<one-paragraph summary>")
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
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nfree\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Context\nClosing free branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with free-mode focus (standard quality review only — code quality, clarity, naming, obvious bugs, missing error handling at boundaries, test coverage gaps). Sprint/plan-level scope concerns do not apply. Return Keep / Concern / Block summary."
)
```

## Steps 5–6: Apply shared close-pipeline reference

The shared close-pipeline reference (Steps 5, 5b, and 6) is emitted by
the preload at the top of this context — see
`scripts/_close_pipeline_shared.md` for the source. Apply those three
steps in order after Step 4, then continue with Step 7 below.

**Free-close override for Step 6 (auto-merge gate):** if ALL of these
hold, skip the shared Step 6's `AskUserQuestion` and proceed directly
to Step 7:
1. Step 5c queued zero ask-user items. Verify deterministically by
   counting Step 5c audit events: every classification appended a
   `concern-classify <id>: <fix|ask>` status event, so a clean run
   means `grep 'concern-classify .*: ask ' <SMM_DIR>/events.jsonl`
   returns zero matches for events filed since the close cycle
   started. Don't rely on recall.
2. No Block-severity finding survived in Step 4's reviewer summary.
3. The full automated test suite passes green AFTER all Step 5c fixes
   landed: run `pytest -n auto` (or the project's documented test
   command) — non-zero exit means fall through to the shared Step 6
   prompt.

When all three conditions hold, print exactly:
"All reviewer findings addressed and tests green — proceeding to merge
without confirmation."
then continue to Step 7. Otherwise apply the shared Step 6
`AskUserQuestion` as written. Free-close merges directly into primary,
so the deterministic green-tests gate is load-bearing — LLM judgment
from Step 5c alone is not sufficient. This matches the v2.37.4
xp-accept auto-accept pattern.

## Step 7: Merge

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

The script chains: merge `--no-ff` → push target (if remote) → delete
source. Any step failing aborts the chain — the source branch always
survives a failed step so the user can resolve and retry. Conflicts
are never auto-resolved; the script's stderr will name the conflict.

## Reporting Back

Tell the user: free branch merged into primary, PR (if created) merged,
local branch deleted. Free-close is complete.
