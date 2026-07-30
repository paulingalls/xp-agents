---
name: xp-free-close
description: >-
  Close ad-hoc work done outside a sprint or plan: review the free branch
  diff and merge it into the integration branch.
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

> **Sequential discipline.** The harness batches independent tool calls in
> parallel; this skill is step-gated. Run Step 1 → 2 → 3 → 4 → 4b → 4.5 → 5–6 → 7
> strictly, one step per turn — make the call, observe, then decide the next.
> Don't batch a step with the one that depends on it (e.g. pushing or merging
> before the forked xp-close-reviewer returns); never spawn the same subagent
> twice. Independent read-only calls may still batch.

The preload above surfaces `SMM_DIR`, `CURRENT_BRANCH`, `TARGET_BRANCH`, `GH_AVAILABLE`, and `WORKTREE_CLEAN`. `TARGET_BRANCH` is the recorded plan branch when `execution_plan.json` sets one (and that branch exists locally), else the primary integration branch (sprint-close parity) — a free branch forked off a plan branch merges back to the plan branch, never to main. Shared pipeline lives in `${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

**Commit trailer reminder — this is the ONLY leg that closes a Try.** When a commit on this free branch lands a carried retro Try (one adopted via `/xp-work-selection adopt`), the commit body **must** include `Resolves-Event: <try-id>`. Adoption now *links* its Try rather than closing it — deliberately, so that taking work on cannot close the item that verifies the work landed. There is no cascade to fall back on: without the trailer, the Try stays open forever and the retro agent keeps carrying it as adopted-but-never-landed.

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
  prompt: "SMM_DIR=<SMM_DIR>\nSYSTEM_CONTEXT_RENDERED=<SYSTEM_CONTEXT_RENDERED>\n\n## Mode\nfree\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Close Cycle ID\n<CLOSE_CYCLE_ID>\n\n## Context\nClosing free branch <CURRENT_BRANCH> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with free-mode focus (standard quality review only — code quality, clarity, naming, obvious bugs, missing error handling at boundaries, test coverage gaps). Sprint/plan-level scope concerns do not apply. Return Keep / Concern / Block summary."
)
```

## Steps 5–6b: Apply shared close-pipeline reference

The shared close-pipeline reference (Steps 5, 5b, 6, 6b) is emitted by the preload at the top of this context — see `scripts/_close_pipeline_shared.md` for the source. Apply those four steps in order after Step 4.5, then continue with Step 7 below.

**Free-close override for Step 6 (auto-merge gate):** if ALL of these hold, skip the shared Step 6's `AskUserQuestion` (Step 6b still runs):

1. Step 5c queued zero ask-user items. Verify via the canonical structured filter:
   ```bash
   ASK_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
     --smm-dir <SMM_DIR> count-classifications \
     --route ask --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
   ```
   `<CLOSE_CYCLE_ID>` and `<CLOSE_START_TS>` are emitted by the preload (captured at close-cycle start). `--cycle-id` excludes concern_classify events tagged with a DIFFERENT close-cycle, so concurrent close-cycles in other teammate worktrees don't leak in (SMM is shared across worktrees). An UNTAGGED event is still counted — the count fails closed rather than silently dropping an ask-route the gate must see — so `--since-ts` is the bound that keeps pre-cycle events out. Test numerically: `[ "$ASK_COUNT" -gt 0 ]` → fall through to the shared Step 6 prompt.

2. No open high-severity concern recorded during Step 4.5, verified via the
   canonical structured filter:
   ```bash
   HIGH_CONCERN_COUNT=$(git diff --no-renames --name-only -z <TARGET_BRANCH>...<CURRENT_BRANCH> \
     | python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
     --smm-dir <SMM_DIR> count-concerns --diff-paths - \
     --severity high --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
   ```
   `--diff-paths -` drops an untagged concern whose recorded files this close never touches, so a concurrent teammate's unrelated open defect cannot abort a clean close; an empty or unreadable diff counts everything (fail closed). Name both branches rather than `HEAD` so the range does not depend on your checkout.
   Test numerically: `[ "$HIGH_CONCERN_COUNT" -gt 0 ]` → fall through to the
   shared Step 6 prompt.

3. The preload emitted a non-empty `TEST_COMMAND=...` line (sourced from `system_context.stack.test_command`) AND running that command AFTER all Step 5c fixes landed exits 0. Any non-zero exit means tests aren't green — fall through to the shared Step 6 prompt.

4. Step 5c classified zero `design_decision` findings — even if the classifier routed one to `fix`. Free-close merges into an integration branch (plan or primary), and architectural calls deserve a human checkpoint regardless of the classifier's route choice. Verify via:
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
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH> \
  --smm-dir <SMM_DIR>
```

Any failing step aborts the chain — source intact for retry. Conflicts are never auto-resolved.

## Reporting Back

**Surface the merge's trailer advisory.** The merge step's `close_common.py merge` prints a `Resolves-Event:` trailer advisory to stdout when eligible commits fall below the trailer target (fail-open — it never blocks the merge). Tool output is invisible to the user, so if the merge printed that advisory, relay it verbatim — the named commits are still in reach to add trailers.

Tell the user: free branch merged into `<TARGET_BRANCH>`, PR (if created) merged, local branch deleted. Free-close is complete.
