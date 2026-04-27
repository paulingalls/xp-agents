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
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Free Close

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. Use these values verbatim — do
not recompute them. `TARGET_BRANCH` is the primary integration branch
(free-close merges a free branch → primary).

## Step 1: Pre-flight

- If `WORKTREE_CLEAN=false`: **refuse to proceed**. Tell the user the
  working tree must be clean (commit or stash uncommitted changes) and
  stop. Free-close never runs against a dirty tree.
- If `CURRENT_BRANCH == TARGET_BRANCH`: **refuse to proceed**. The
  current branch IS the primary — there is no free branch to merge.
  Tell the user and stop.

## Step 2: Push the free branch

If `git remote` returns at least one remote, push so the PR can
reference the branch and others can review:

```bash
git push -u origin <CURRENT_BRANCH>
```

If no remote is configured, skip the push and note it (this is a
local-only free close).

## Step 3: PR creation (gh-aware)

If `GH_AVAILABLE=true`, create the pull request. `gh pr create` prints
the new PR's URL on success — capture it and derive the PR number from
the URL tail:

```bash
PR_URL=$(gh pr create --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "<short title for the free work>" --body "<one-paragraph summary>")
PR_NUMBER="${PR_URL##*/}"
```

If `GH_AVAILABLE=false`, **skip the PR step** and tell the user the gh
CLI was not on PATH so PR creation was bypassed. The reviewer will
diff locally instead.

## Step 4: Fork the close-reviewer

Invoke the forked review agent. Pass `SMM_DIR` and the four close-review
fields (mode, source branch, target branch, diff command) inline as
prompt sections — the agent reads them from the prompt. There is no
SubagentStart injection.

When `GH_AVAILABLE=true`:

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nfree\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\ngh pr diff <PR_NUMBER>\n\n## Context\nClosing free branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_NUMBER>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with free-mode focus (standard quality review only — code quality, clarity, naming, obvious bugs, missing error handling at boundaries, test coverage gaps). Sprint/plan-level scope concerns do not apply. Return Keep / Concern / Block summary."
)
```

When `GH_AVAILABLE=false` (PR was skipped):

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nfree\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\ngit diff <TARGET_BRANCH>...HEAD\n\n## Context\nClosing free branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR not created (no gh).\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with free-mode focus (standard quality review only — code quality, clarity, naming, obvious bugs, missing error handling at boundaries, test coverage gaps). Sprint/plan-level scope concerns do not apply. Return Keep / Concern / Block summary."
)
```

## Step 5: Present findings

Output the reviewer's Keep / Concern / Block summary verbatim to the
user. The tool result is not visible to them — surface it as text.

## Step 6: Confirm the merge

Use `AskUserQuestion` to ask whether to proceed with the merge. Two
options: "Merge into ${TARGET_BRANCH}" or "Abort — fix concerns first".

If the user picks abort, stop here. The branch and PR (if any) stay
intact for follow-up work.

## Step 7: Merge and clean up

On confirmation, merge with --no-ff, push the target so the PR closes
on GitHub, then chain delete behind the push's success. Always pass
`--target` explicitly — branching.py requires it. The `&&` chain
guarantees push only runs after a clean merge and delete only runs
after a clean push:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  merge-branch --cwd . --branch <CURRENT_BRANCH> --target <TARGET_BRANCH> && \
git push origin <TARGET_BRANCH> && \
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  delete --cwd . --branch <CURRENT_BRANCH>
```

If `git remote` returned no remote in Step 2, omit the `git push origin
<TARGET_BRANCH>` line — the merge stays local and the PR step was
skipped, so there is no PR to close.

Each command exits non-zero on failure, short-circuiting the chain so
the branch survives if the merge fails.

If the merge fails, surface the failure (stderr + stdout from the
merge call already include the source/target branch names and the
conflict marker) and **do not** push or delete — the user needs to
resolve the conflict on the still-existing branch. Conflicts are never
auto-resolved.

## Reporting Back

Tell the user: free branch merged into primary, PR (if created) merged,
local branch deleted. Free-close is complete.
