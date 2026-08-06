---
name: xp-sprint-close
description: >-
  Close a sprint branch: cross-cutting review, then merge into the target
  with cleanup. Auto-invoked at the end of /xp-sprint-review.
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
  - Bash(python3 */smm/sprint_cli.py *)
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Sprint Close

> **Sequential discipline.** Run Step 0 → 1 → 2 → 3 → 4 → 4b → 4.5 → 5–6 → 7 → 8
> one per turn: make the call, observe, then decide the next. Never batch a step
> with one that depends on it, and never spawn the same subagent twice;
> independent read-only calls may batch.

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`,
`GH_AVAILABLE`, and `WORKTREE_CLEAN`. Shared pipeline lives in
`${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

**Commit trailer reminder — this is the ONLY leg that closes a Try.** A commit on this sprint branch that lands a carried retro Try (one adopted via `/xp-work-selection adopt`) **must** include `Resolves-Event: <try-id>` in its body. Adoption only *links* its Try — taking work on must not close the item that verifies the work landed — and there is no cascade to fall back on: without the trailer the Try stays open forever, carried as adopted-but-never-landed.

## Step 0: Verify-acceptance gate

The preload surfaces `VERIFY_STATUS` (`green`/`red`/`unverified`/`none`) — the last sprint-verify rerun's status. `green`/`none` proceed to Step 1 (`none` = nothing verify-bearing to gate). `unverified` means the sprint carries verify-bearing acceptance and no rerun recorded a result (usually one killed by its tool bound before emitting): gate as `red` below, but tell the user to **run `/xp-sprint-review`**, not to fix failures. `red` means acceptance items failed **or never ran** (the batch budget stopped the rerun — those lines read `not run`): **refuse the merge** — stop and tell the user to fix the failures, or raise the batch budget for the not-run ones, and re-run `/xp-sprint-review`; or override via `/xp-sprint-close --force-close <reason>`. On `--force-close <reason>`, record the bypass as debt, then continue:

```bash
FAILING=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/verify_acceptance.py --query-verify-status --smm-dir <SMM_DIR> | tail -n +2 | head -c 240) || true
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> --type "debt" --agent "xp-sprint-close" \
  --content "Force-close <reason>: merged sprint with red verify items: $FAILING" --files '["<SMM_DIR>/sprint.json"]'
```

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd . --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

If the exit code is non-zero, **stop**. The script emitted the reason on
stderr (dirty worktree or `<CURRENT_BRANCH>` IS `<TARGET_BRANCH>`); relay
it so the user can commit/stash or change branches.

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
  prompt: "SMM_DIR=<SMM_DIR>\nSYSTEM_CONTEXT_RENDERED=<SYSTEM_CONTEXT_RENDERED>\n\n## Mode\nsprint\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Close Cycle ID\n<CLOSE_CYCLE_ID>\n\n## Context\nClosing sprint branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with sprint-mode focus (cross-cutting changes, duplication across stories, API coherence, constraint drift), plus Step 3b in every mode. Return Keep / Concern / Block summary."
)
```

## Steps 5–6b: Apply shared close-pipeline reference

The shared reference (Steps 5, 5b, 6, 6b) is emitted by the preload —
see `scripts/_close_pipeline_shared.md`. Apply in order after Step 4.5,
then continue with Step 7 below.

**Sprint-close addendum to Step 6:** if the user aborts at the shared Step 6 prompt, the sprint stays unarchived — Step 7 below only runs on a confirmed merge.

## Step 7: Merge and archive

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH> \
  --verify-gate acceptance --archive-sprint --smm-dir <SMM_DIR>
```

`--verify-gate acceptance` is a deterministic backstop that refuses the merge on a red verify status; on the Step 0 `--force-close` path also pass `--force-verify`. The archive runs INSIDE the merge, after the target push and before the branch delete — so any step that can still fail leaves sprint.json (the acceptance gate's only input) in place, and a failed archive leaves the source branch intact; re-running this exact command re-merges idempotently and retries the archive. It snapshots the completed sprint under `sprints/` before the next `/xp-sprint-start` overwrites `sprint.json`. Conflicts are never auto-resolved.

## Step 8: Plan-close chain (if applicable)

After merge cleanup, check whether the sprint just shipped the last milestone of a plan-branch plan. The gate fires only when both checks succeed — `get-branch` prints non-empty AND `is-plan-complete` exits 0:

```bash
PLAN_BRANCH=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> get-branch) \
  && [ -n "$PLAN_BRANCH" ] \
  && python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> is-plan-complete
```

If the gate exits 0, invoke `/xp-plan-close`. It runs in the same main agent context; the user confirms each merge inside.

If the gate exits non-zero, skip the chain and report sprint-close complete.

## Reporting Back

**Surface the merge's trailer advisory.** `close_common.py merge` prints a `Resolves-Event:` advisory to stdout when eligible commits fall below the trailer target (fail-open — it never blocks the merge). Tool output is invisible to the user, so relay any such advisory verbatim — the named commits are still in reach to add trailers.

Tell the user: branch merged into target, PR (if created) merged, local
branch deleted, sprint.json archived under `<SMM_DIR>/sprints/`.
Sprint-close is complete.
