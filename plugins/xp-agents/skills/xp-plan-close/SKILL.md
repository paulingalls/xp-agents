---
name: xp-plan-close
description: >-
  Push the plan branch, fork xp-close-reviewer for plan-level review,
  and merge into the primary branch with archive. Auto-invoked by
  /xp-sprint-close after the last milestone of a plan-branch plan
  ships; degrades gracefully when gh is unavailable.
allowed-tools:
  - Read
  - Write
  - Bash
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */scripts/branching.py *)
  - Bash(python3 */smm/plan_cli.py *)
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Plan Close

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. Use these values verbatim — do
not recompute them. `TARGET_BRANCH` is the primary integration branch
(plan-close merges plan → primary).

## Step 1: Pre-flight

- If `WORKTREE_CLEAN=false`: **refuse to proceed**. Tell the user the
  working tree must be clean (commit or stash uncommitted changes) and
  stop. Plan-close never runs against a dirty tree.
- If `CURRENT_BRANCH == TARGET_BRANCH`: **refuse to proceed**. The
  current branch IS the primary — there is no plan branch to merge.
  Tell the user and stop.

## Step 2: Push the plan branch

If `git remote` returns at least one remote, push so the PR can
reference the branch and others can review:

```bash
git push -u origin <CURRENT_BRANCH>
```

If no remote is configured, skip the push and note it (this is a
local-only plan close).

## Step 3: PR creation (gh-aware)

If `GH_AVAILABLE=true`, create the pull request. `gh pr create` prints
the new PR's URL on success — capture it and derive the PR number from
the URL tail:

```bash
PR_URL=$(gh pr create --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "<plan title>" --body "<plan summary>")
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

The `diff_command` shape depends on `GH_AVAILABLE`: when `true`, use
`gh pr diff <PR_NUMBER>`; when `false`, use `git diff <TARGET_BRANCH>...HEAD`.

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nplan\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\ngh pr diff <PR_NUMBER>   # or: git diff <TARGET_BRANCH>...HEAD when no PR\n\n## Context\nClosing plan branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_NUMBER or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with plan-mode focus (architectural coherence across the whole plan, accumulated debt, security posture of the cumulative diff, decisions whose rationale weakened). Return Keep / Concern / Block summary."
)
```

## Step 5: Present findings

Output the reviewer's Keep / Concern / Block summary verbatim to the
user. The tool result is not visible to them — surface it as text.

## Step 6: Confirm the merge

Use `AskUserQuestion` to ask whether to proceed with the merge. Two
options: "Merge into ${TARGET_BRANCH}" or "Abort — fix concerns first".

If the user picks abort, stop here. The branch and PR (if any) stay
intact for follow-up work; the plan stays unarchived.

## Step 7: Merge, archive, and clean up

On confirmation, merge with --no-ff and chain archive + delete behind
the merge's success. Always pass `--target` explicitly — branching.py
requires it. The `&&` chain guarantees archive only runs after a clean
merge and delete only runs after a clean archive:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  merge-branch --cwd . --branch <CURRENT_BRANCH> --target <TARGET_BRANCH> && \
python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> archive && \
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  delete --cwd . --branch <CURRENT_BRANCH>
```

Each command exits non-zero on failure, short-circuiting the chain so
the plan stays intact and the branch survives if any step fails.

If the merge fails, surface the failure (stderr + stdout from the
merge call already include the source/target branch names and the
conflict marker) and **do not** archive the plan or delete the
branch — the user needs to resolve the conflict on the still-existing
branch with the plan still in place. Conflicts are never auto-resolved.

## Reporting Back

Tell the user: plan branch merged into primary, PR (if created) merged,
local branch deleted, execution_plan.json archived under
`<SMM_DIR>/plans/`. Plan-close is complete.
