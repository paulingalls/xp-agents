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
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. Shared pipeline lives in
`${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

**Commit trailer reminder.** When a commit on this sprint branch closed a carried retro Try (an adopted `retro-try-*` decision from this or a prior session), the commit body should include `Resolves-Event: <try-id-or-ref>` so `try_status` closes the loop. Cascade closure via the adoption decision's `metadata.resolves` covers most cases; explicit trailers cover the rest.

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

Stdout is `pushed: <branch>` or `skipped: no remote configured`.

## Step 3: PR creation

```bash
PR_OUTPUT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py create-pr \
  --cwd . --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "<sprint goal>" --body "<sprint summary>")
```

`PR_OUTPUT` is a PR number or `skipped: no gh on PATH`.

## Step 4: Apply shared Security Review

Apply the shared `### Step 4: Security Review` block above with
`<close-mode>` → `sprint` and `<close-skill-name>` → `xp-sprint-close`.

## Step 4.5: Fork the close-reviewer

Compute the diff command:

```bash
DIFF_CMD=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py diff-command \
  --pr-output "$PR_OUTPUT" --target <TARGET_BRANCH>)
```

Substitute the captured value as `<DIFF_CMD>` in the agent prompt below.

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\n\n## Mode\nsprint\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Close Cycle ID\n<CLOSE_CYCLE_ID>\n\n## Context\nClosing sprint branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with sprint-mode focus (cross-cutting changes, duplication across stories, API coherence, drift from in-flight constraints). Return Keep / Concern / Block summary."
)
```

## Steps 5–6: Apply shared close-pipeline reference

The shared close-pipeline reference (Steps 5, 5b, and 6) is emitted by
the preload at the top of this context — see
`scripts/_close_pipeline_shared.md` for the source. Apply those three
steps in order after Step 4.5, then continue with Step 7 below.

## Step 7: Merge

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

Any failing step aborts the chain — source intact for retry. Conflicts are never auto-resolved.

## Step 8: Plan-close chain (if applicable)

After merge cleanup completes, check whether the sprint just shipped the last milestone of a plan-branch plan. The gate fires only when both checks succeed — `get-branch` prints non-empty AND `is-plan-complete` exits 0:

```bash
PLAN_BRANCH=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> get-branch) \
  && [ -n "$PLAN_BRANCH" ] \
  && python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> is-plan-complete
```

If the gate exits 0, invoke `/xp-plan-close` — it pushes the plan branch, forks the close-reviewer in plan mode, merges plan → primary, archives the plan, and cleans up. Runs in the same main agent context; the user confirms each merge inside.

If the gate exits non-zero, skip the chain and report sprint-close complete.

## Reporting Back

Tell the user: branch merged into target, PR (if created) merged, local
branch deleted. Sprint-close is complete.
