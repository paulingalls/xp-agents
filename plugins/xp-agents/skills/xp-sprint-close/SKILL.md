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
  - Bash(python3 */smm/plan_cli.py *)
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Sprint Close

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. Use these values verbatim — do
not recompute them.

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

## Step 4: Fork the close-reviewer

Invoke the forked review agent. Pass `SMM_DIR` and the four close-review
fields (mode, source branch, target branch, diff command) inline as
prompt sections — the agent reads them from the prompt. There is no
SubagentStart injection.

When `GH_AVAILABLE=true`:

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nsprint\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\ngh pr diff <PR_NUMBER>\n\n## Context\nClosing sprint branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_NUMBER>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with sprint-mode focus (cross-cutting changes, duplication across stories, API coherence, drift from in-flight constraints). Return Keep / Concern / Block summary."
)
```

When `GH_AVAILABLE=false` (PR was skipped):

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nsprint\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\ngit diff <TARGET_BRANCH>...HEAD\n\n## Context\nClosing sprint branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR not created (no gh).\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with sprint-mode focus (cross-cutting changes, duplication across stories, API coherence, drift from in-flight constraints). Return Keep / Concern / Block summary."
)
```

## Step 5: Present findings

Output the reviewer's Keep / Concern / Block summary verbatim to the
user. The tool result is not visible to them — surface it as text.

## Step 5b: Resolve Addressed Concerns

Scan for open concerns that were likely addressed by this sprint's work.
Run the triage preload to find them:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/triage_preload.py \
  --smm-dir <SMM_DIR>
```

Focus on the "Open Concerns" section of the output. For each concern
annotated with **LIKELY ADDRESSED**: use your session context and the
listed commits to judge whether the concern was genuinely fixed. When
confident, auto-resolve:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py \
  triage-drop --smm-dir <SMM_DIR> --event-id <event-id>
```

When in doubt, leave the concern open — it will surface at the next
kickoff for manual triage. Report how many concerns were auto-resolved
alongside the reviewer findings before asking the user to confirm the
merge.

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

If the merge fails, surface the failure (stderr + stdout from the merge
call already include the source/target branch names and the conflict
marker) and **do not** push or delete — the user needs to resolve the
conflict on the still-existing branch. Conflicts are never auto-resolved.

## Step 8: Plan-close chain (if applicable)

After the merge cleanup completes, check whether the sprint just shipped
the last milestone of a plan-branch plan. The gate fires only when both
checks succeed — `get-branch` prints non-empty AND `is-plan-complete`
exits 0:

```bash
PLAN_BRANCH=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> get-branch) \
  && [ -n "$PLAN_BRANCH" ] \
  && python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> is-plan-complete
```

- `get-branch` prints the recorded plan branch (empty when the plan
  is not on a plan branch).
- `is-plan-complete` exits 0 when every milestone is delivered or
  deferred, non-zero otherwise.

If the gate above exits 0, invoke `/xp-plan-close` to push the plan
branch, fork the close-reviewer in plan mode, present findings, merge
plan → primary, archive the plan, and clean up. The chain runs in the
same main agent context — the user confirms each merge inside.

If the gate exits non-zero, skip the chain and report sprint-close
complete (the section below).

## Reporting Back

Tell the user: branch merged into target, PR (if created) merged, local
branch deleted. Sprint-close is complete.
