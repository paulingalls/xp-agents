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

Free-close does NOT run the LIKELY ADDRESSED concern auto-resolve step
— free branches are ad-hoc and don't carry sprint/plan-tracked
concerns.

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

## Step 5: Present findings

Output the reviewer's Keep / Concern / Block summary verbatim to the
user. The tool result is not visible to them — surface it as text.

## Step 6: Confirm the merge

Use `AskUserQuestion` to ask whether to proceed with the merge. Two
options: "Merge into ${TARGET_BRANCH}" or "Abort — fix concerns first".

**If the close-reviewer's prose summary above contains any Block
finding (recorded by xp-close-reviewer at severity high per Step 3.5),
list "Abort — fix concerns first" as the FIRST option and append
"(Recommended)" to its label.** This honors the xp-close-reviewer
Step 3.5 contract: Block findings flip the merge default to Abort.
The user can still pick Merge to override. When no Block was filed,
keep the default ordering (Merge first).

If the user picks abort, stop here. The branch and PR (if any) stay
intact for follow-up work.

If the preload included a `### HOOK_GUIDANCE` section, follow it
before confirming the merge.

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
