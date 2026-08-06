---
name: xp-plan-close
description: >-
  Close a plan branch: review the plan-level diff and merge into primary
  with archive. Auto-invoked after a plan's last milestone ships.
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
  - Skill
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Plan Close

> **Sequential discipline.** Run Step 1 → 2 → 3 → 4 → 4b → 4.5 → 5–6 → 7 → 8
> one per turn: make the call, observe, then decide the next. Never batch a step
> with one that depends on it, and never spawn the same subagent twice;
> independent read-only calls may batch.

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. `TARGET_BRANCH` is the primary
integration branch (plan-close merges plan → primary). Shared pipeline
lives in `${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd . --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

If the exit code is non-zero, **stop**. The script emitted the reason on
stderr (dirty worktree or `<CURRENT_BRANCH>` IS `<TARGET_BRANCH>`).

## Step 2: Push the plan branch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py push \
  --cwd . --branch <CURRENT_BRANCH>
```

## Step 3: PR creation

```bash
PR_OUTPUT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py create-pr \
  --cwd . --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "<plan title>" --body "<plan summary>")
```

`PR_OUTPUT` is a PR number or `skipped: no gh on PATH`.

## Step 4: Apply shared Security Review

Apply the shared `### Step 4: Security Review` block above with
`<close-mode>` → `plan` and `<close-skill-name>` → `xp-plan-close`.

## Step 4b: Apply shared Full Code Review (conditional)

Apply the shared `### Step 4b: Full code review (conditional)` block above.

## Step 4.5: Fork the close-reviewer

Compute the diff command:

```bash
DIFF_CMD=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py diff-command \
  --target <TARGET_BRANCH> --source <CURRENT_BRANCH>)
```

Substitute the captured value as `<DIFF_CMD>` in the agent prompt below.

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\nSYSTEM_CONTEXT_RENDERED=<SYSTEM_CONTEXT_RENDERED>\n\n## Mode\nplan\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Close Cycle ID\n<CLOSE_CYCLE_ID>\n\n## Context\nClosing plan branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with plan-mode focus (architectural coherence across the whole plan, accumulated debt, decisions whose rationale weakened), plus Step 3b Prose Hygiene, which applies in every mode. Return Keep / Concern / Block summary."
)
```

## Steps 5–6b: Apply shared close-pipeline reference

The shared reference (Steps 5, 5b, 6, 6b) is emitted by the preload —
see `scripts/_close_pipeline_shared.md`. Apply in order after Step 4.5,
then continue with Step 7 below.

**Plan-close addendum to Step 6:** if the user aborts at the shared Step 6 prompt, the plan stays unarchived — Step 7 below only runs on a confirmed merge.

## Step 7: Merge and archive

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH> \
  --smm-dir <SMM_DIR> && \
python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> archive
```

Any failing step aborts the chain — plan stays unarchived and the branch alive for retry.

## Step 8: Update System Context

A completed plan may have changed the project's architecture, conventions,
or structure; refresh `system_context.json` so the next planning cycle
starts from an accurate baseline.

Invoke `/xp-system-context` via the `Skill` tool, wait for completion, and
output the key findings to the user.

If the skill fails, record a concern and continue — do not block plan-close:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "xp-plan-close" --severity "medium" \
  --content "system-context refresh failed after plan-close — run /xp-system-context manually"
```

## Reporting Back

**Surface the merge's trailer advisory.** `close_common.py merge` prints a `Resolves-Event:` advisory to stdout when eligible commits fall below the trailer target (fail-open — it never blocks the merge). Tool output is invisible to the user, so relay any such advisory verbatim — the named commits are still in reach to add trailers.

Tell the user: plan branch merged into primary, PR (if created) merged,
local branch deleted, execution_plan.json archived under
`<SMM_DIR>/plans/`, system context refreshed. Plan-close is complete.
