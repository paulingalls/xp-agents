---
name: xp-sprint-close
description: >-
  Push the sprint branch, fork xp-close-reviewer for cross-cutting review,
  and merge into the target with cleanup. Auto-invoked at the end of
  /xp-sprint-review; degrades gracefully when gh is unavailable.
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

# Sprint Close

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, `WORKTREE_CLEAN`, and `REVIEW_INPUT`. Use these values
verbatim — do not recompute them.

## Step 1: Pre-flight

- If `WORKTREE_CLEAN=false`: **refuse to proceed**. Tell the user the
  working tree must be clean (commit or stash uncommitted changes) and
  stop. Sprint-close never runs against a dirty tree.
- If `CURRENT_BRANCH == TARGET_BRANCH`: **refuse to proceed**. The
  current branch IS the target — nothing to merge. Tell the user and stop.

## Step 2: Push the sprint branch

If `git remote` returns at least one remote, push so the PR can reference
the branch and others can review:

```bash
git push -u origin <CURRENT_BRANCH>
```

If no remote is configured, skip the push and note it (this is a local-
only sprint).

## Step 3: PR creation (gh-aware)

If `GH_AVAILABLE=true`, create the pull request. `gh pr create` prints
the new PR's URL on success — capture it and derive the PR number from
the URL tail (`gh pr create` does not support `--json`):

```bash
PR_URL=$(gh pr create --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "<sprint goal>" --body "<sprint summary>")
PR_NUMBER="${PR_URL##*/}"
```

If `GH_AVAILABLE=false`, **skip the PR step** and tell the user the gh
CLI was not on PATH so PR creation was bypassed. The reviewer will diff
locally instead.

## Step 4: Write the close-review input

Write a JSON file at `<REVIEW_INPUT>` (the per-invocation tempfile path
the preload echoed) with the four fields the close-reviewer agent
reads. The shape depends on `GH_AVAILABLE`:

When `GH_AVAILABLE=true`:

```json
{
  "mode": "sprint",
  "source_branch": "<CURRENT_BRANCH>",
  "target_branch": "<TARGET_BRANCH>",
  "diff_command": "gh pr diff <PR_NUMBER>"
}
```

When `GH_AVAILABLE=false` (PR was skipped):

```json
{
  "mode": "sprint",
  "source_branch": "<CURRENT_BRANCH>",
  "target_branch": "<TARGET_BRANCH>",
  "diff_command": "git diff <TARGET_BRANCH>...HEAD"
}
```

## Step 5: Fork the close-reviewer

Invoke the forked review agent. Pass `SMM_DIR` and the per-invocation
`REVIEW_INPUT` path (from the preload) explicitly in the prompt — the
agent reads them from there. There is no SubagentStart injection.

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\nREVIEW_INPUT=<REVIEW_INPUT>\n\n## Mode\nsprint\n\n## Context\nClosing sprint branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_NUMBER or 'not created (no gh)'>.\n\n## Instructions\nRead REVIEW_INPUT, run diff_command, analyze cumulative diff with sprint-mode focus (cross-cutting changes, duplication across stories, API coherence, drift from in-flight constraints). Return Keep / Concern / Block summary."
)
```

## Step 6: Present findings

Output the reviewer's Keep / Concern / Block summary verbatim to the
user. The tool result is not visible to them — surface it as text.

## Step 7: Confirm the merge

Use `AskUserQuestion` to ask whether to proceed with the merge. Two
options: "Merge into ${TARGET_BRANCH}" or "Abort — fix concerns first".

If the user picks abort, stop here. The branch and PR (if any) stay
intact for follow-up work.

## Step 8: Merge and clean up

On confirmation, merge with --no-ff and chain delete behind the merge's
success. Always pass `--target` explicitly — branching.py requires it.
The `&&` chain guarantees delete only runs after a clean merge:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  merge-branch --cwd . --branch <CURRENT_BRANCH> --target <TARGET_BRANCH> && \
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  delete --cwd . --branch <CURRENT_BRANCH>
```

If the merge fails, surface the failure (stderr + stdout from the merge
call already include the source/target branch names and the conflict
marker) and **do not** delete the branch — the user needs to resolve the
conflict on the still-existing branch. Conflicts are never auto-resolved.

## Reporting Back

Tell the user: branch merged into target, PR (if created) merged, local
branch deleted. Sprint-close is complete.
