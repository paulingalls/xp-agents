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
  - Bash(python3 */scripts/close_common.py *)
  - Bash(python3 */smm/plan_cli.py *)
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Sprint Close

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. Use these values verbatim — do
not recompute them. The shared close pipeline lives in
`${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`; the four mechanical
steps (preflight, push, create-pr, merge) are subcommand invocations
below. Detection (no remote, no gh) is internal to the script.

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd . --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

If the exit code is non-zero, **stop**. The script emitted the reason on
stderr (dirty worktree or `<CURRENT_BRANCH>` IS `<TARGET_BRANCH>`). Tell
the user to commit/stash or change branches.

## Step 2: Push the sprint branch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py push \
  --cwd . --branch <CURRENT_BRANCH>
```

Stdout is either `pushed: <branch>` or `skipped: no remote configured`
— surface to the user so they know whether the branch was pushed.

## Step 3: PR creation

```bash
PR_OUTPUT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py create-pr \
  --cwd . --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "<sprint goal>" --body "<sprint summary>")
```

`PR_OUTPUT` is either a PR number (e.g. `4242`) or `skipped: no gh on
PATH`. The reviewer fork (Step 4) chooses its diff command based on
this value.

## Step 4: Fork the close-reviewer

Compute the diff command:

```bash
DIFF_CMD=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py diff-command \
  --pr-output "$PR_OUTPUT" --target <TARGET_BRANCH>)
```

Substitute the captured value as `<DIFF_CMD>` in the agent prompt below.

Invoke the forked review agent. Pass `SMM_DIR` and the four close-review
fields (mode, source branch, target branch, diff command) inline as
prompt sections — the agent reads them from the prompt.

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nsprint\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Context\nClosing sprint branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with sprint-mode focus (cross-cutting changes, duplication across stories, API coherence, drift from in-flight constraints). Return Keep / Concern / Block summary."
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

If the preload reports `PRE_COMMIT_HOOK=absent`, the merge in Step 7
won't fire any project tests. Before confirming, run the project's
test command (look in CLAUDE.md) so the merged state is verified.
When `PRE_COMMIT_HOOK=present` the project's hook runs on the merge
commit and this step is unnecessary.

## Step 7: Merge

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

The script chains: merge `--no-ff` → push target (if remote) → delete
source. Any step failing aborts the chain — the source branch always
survives a failed step so the user can resolve and retry. Conflicts are
never auto-resolved; the script's stderr will name the conflict.

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
