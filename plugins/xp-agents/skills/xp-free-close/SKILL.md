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

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`, `GH_AVAILABLE`, and `WORKTREE_CLEAN`. `TARGET_BRANCH` is the primary integration branch (free-close merges a free branch → primary). Shared pipeline lives in `${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

**Commit trailer reminder.** When a commit on this free branch closed a carried retro Try (an adopted `retro-try-*` decision from this or a prior session), the commit body should include `Resolves-Event: <try-id-or-ref>` so `try_status` closes the loop. Cascade closure via the adoption decision's `metadata.resolves` covers most cases; explicit trailers cover the rest.

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd . --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

If the exit code is non-zero, **stop** — script emitted the reason on stderr (dirty worktree or `<CURRENT_BRANCH>` IS `<TARGET_BRANCH>`).

## Step 2: Push the free branch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py push \
  --cwd . --branch <CURRENT_BRANCH>
```

## Step 3: PR creation

```bash
PR_OUTPUT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py create-pr \
  --cwd . --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "<short title for the free work>" --body "<one-paragraph summary>")
```

`PR_OUTPUT` is a PR number or `skipped: no gh on PATH`.

## Step 4: Apply shared Security Review

Apply the shared `### Step 4: Security Review` block above with `<close-mode>` → `free` and `<close-skill-name>` → `xp-free-close`.

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
  prompt: "SMM_DIR=<SMM_DIR>\nSYSTEM_CONTEXT_RENDERED=<SYSTEM_CONTEXT_RENDERED>\n\n## Mode\nfree\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Close Cycle ID\n<CLOSE_CYCLE_ID>\n\n## Context\nClosing free branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with free-mode focus (standard quality review only — code quality, clarity, naming, obvious bugs, missing error handling at boundaries, test coverage gaps). Sprint/plan-level scope concerns do not apply. Return Keep / Concern / Block summary."
)
```

## Steps 5–6: Apply shared close-pipeline reference

The shared close-pipeline reference (Steps 5, 5b, and 6) is emitted by the preload at the top of this context — see `scripts/_close_pipeline_shared.md` for the source. Apply those three steps in order after Step 4.5, then continue with Step 7 below.

**Free-close override for Step 6 (auto-merge gate):** if ALL of these hold, skip the shared Step 6's `AskUserQuestion` and proceed directly to Step 7:

1. Step 5c queued zero ask-user items. Verify via the canonical structured filter:
   ```bash
   ASK_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
     --smm-dir <SMM_DIR> count-classifications \
     --route ask --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
   ```
   `<CLOSE_CYCLE_ID>` and `<CLOSE_START_TS>` are emitted by the preload (captured at close-cycle start). `--cycle-id` is the strict scoper — it prevents concurrent close-cycles in other teammate worktrees from leaking concern_classify events into this count (SMM is shared across worktrees). Test numerically: `[ "$ASK_COUNT" -gt 0 ]` → fall through to the shared Step 6 prompt.

2. No Block-severity finding survived in Step 4.5's reviewer summary.

3. The preload emitted a non-empty `TEST_COMMAND=...` line (sourced from `system_context.stack.test_command`) AND running that command AFTER all Step 5c fixes landed exits 0. Any non-zero exit means tests aren't green — fall through to the shared Step 6 prompt.

4. Step 5c classified zero `design_decision` findings — even if the classifier routed one to `fix`. Free-close merges to primary, and architectural calls deserve a human checkpoint regardless of the classifier's route choice. Verify via:
   ```bash
   DESIGN_DECISION_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
     --smm-dir <SMM_DIR> count-classifications \
     --category design_decision --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
   ```
   Test numerically: `[ "$DESIGN_DECISION_COUNT" -gt 0 ]` → fall through to the shared Step 6 prompt.

When `TEST_COMMAND` is empty (the project hasn't configured a test command), the gate cannot fire. Print this two-line discovery hint before falling through to the shared Step 6 prompt:

```
Auto-merge disabled — set stack.test_command in system_context.json to enable.
To set it, pipe the command (JSON-quoted) into the edit-stack-field CLI:
    printf %s '"<your-test-command>"' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> edit-stack-field test_command
```

When all four conditions hold, print exactly:
"All reviewer findings addressed and tests green — proceeding to merge without confirmation."
then continue to Step 7. Otherwise apply the shared Step 6 `AskUserQuestion` as written.

## Step 7: Merge

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

Any failing step aborts the chain — source intact for retry. Conflicts are never auto-resolved.

## Reporting Back

Tell the user: free branch merged into primary, PR (if created) merged, local branch deleted. Free-close is complete.
