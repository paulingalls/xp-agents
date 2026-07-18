---
name: xp-story-close
description: >-
  Per-story close: review the story diff, merge into the sprint base,
  and clean up. Invoked by /xp-accept on each accepted story; the
  next-frontier promotion (via /xp-schedule) and the sprint-review
  dispatch are owned by /xp-accept after its loop completes — single
  source of truth lives there.
allowed-tools:
  - Read
  - Write
  - Bash
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */scripts/branching.py *)
  - Bash(python3 */scripts/close_common.py *)
  - Bash(python3 */smm/sprint_cli.py *)
  - Bash(python3 */scripts/cleanup_teammate.py *)
  - Bash(git push *)
  - Bash(gh pr *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Story Close

> **Sequential discipline.** The harness batches independent tool calls in
> parallel; this skill is step-gated. Run Step 1 → 1b → 1c → 2 → 3 → 4.5 → 5–6 →
> 7 → 7b strictly, one step per turn — make the call, observe, then decide
> the next. Don't batch a step with the one that depends on it (e.g. merging
> before the diff review completes); never spawn the same subagent twice.
> Independent read-only calls may still batch.

The preload above surfaces `SMM_DIR`, `TEAMMATE_CWD`, `CURRENT_BRANCH`,
`TARGET_BRANCH`, `STORY_BASE_UNRESOLVED`, `GH_AVAILABLE`, `WORKTREE_CLEAN`.
`TARGET_BRANCH` is the merge destination — the sprint branch at stage 2+,
primary otherwise. Shared pipeline lives in
`${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py`.

## Step 0: Halt if the merge destination is unresolved

If `STORY_BASE_UNRESOLVED=true`, **STOP. Run no further step.**

`TARGET_BRANCH` is the branch this close merges the story INTO, and the only
value it could have been guessed as is the release branch. There is no safe
degraded close. Report the reason the preload printed: re-cut the sprint branch
(`branching.py create-sprint`) or fix `sprint.json`'s `branch_name`, then
re-run `/xp-story-close`.

`TEAMMATE_CWD` is non-empty when closing a teammate story (orchestrator
sits on the sprint branch; teammate commits live in the teammate's
`worktree-<story-id>` worktree, out of the repo). Requires the story in
`closing` state (set by `/xp-accept` Step 1.5) — the worktree lookup
keys on it. Steps 1 and 3 route `close_common.py` at
`--cwd ${TEAMMATE_CWD:-.}` (they read the story's diff/PR base). Step 2
(push) instead relocates to the main checkout (`--cwd .`) — see Step 2.
Step 7 (merge) ALWAYS runs at orchestrator
cwd (`--cwd .`) — `git merge` checks out the target branch held by the
orchestrator's worktree, so running it from the teammate cwd fails with
`'<target>' is already used by worktree`. Step 7b also runs at
orchestrator cwd (`git worktree` operates on the parent registry).
Solo flow: every step uses orchestrator cwd.

## Step 1: Pre-flight

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py preflight \
  --cwd ${TEAMMATE_CWD:-.} --current <CURRENT_BRANCH> --target <TARGET_BRANCH>
```

Stop on non-zero exit; the script emitted the reason on stderr.

## Step 1b: Validate file_domain

Surface file_domain drift to stderr before the reviewer fork. Default
`XP_FILE_DOMAIN_DRIFT_TOLERANCE=1` absorbs a single drifting file
(set `0` for strict). Do NOT emit a concern event — per convention,
drift is a planning signal that retro surfaces from `cascade_size`;
emitting per-close concerns pollutes the open-event surface. Continue
regardless of drift state.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  validate-domain <story-id> --base <TARGET_BRANCH> \
  --cwd ${TEAMMATE_CWD:-.} >/dev/null || true
```

## Step 1c: Verify-touch gate

Read the preload's `VERIFY_UNTOUCHED` and `VERIFY_DEFERRED`.

If `VERIFY_UNTOUCHED` is non-empty AND `VERIFY_DEFERRED` is `false`,
**refuse the close**: tell the user `no commit touched <VERIFY_UNTOUCHED>`
and stop here — do NOT push, create a PR, or merge. The story branch
needs a commit that touches each declared acceptance-test path, or a
`[verify-deferred] <reason>` commit to defer it (the deferral is
recorded as debt). The customer can re-run `/xp-accept` after adding
the touching (or deferring) commit.

If `VERIFY_DEFERRED` is `true`, the deferral is on record — proceed.
If `VERIFY_UNTOUCHED` is empty, the gate passes — proceed.

## Step 2: Push the story branch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py push \
  --cwd . --branch <CURRENT_BRANCH> --smm-dir <SMM_DIR>
```

Always at orchestrator cwd (`--cwd .`), never the teammate worktree. Pushing
from a teammate worktree fires the project's pre-push hook *there*, where a
fresh worktree has no installed deps (`node_modules`/`.env`/e2e) →
`ERR_MODULE_NOT_FOUND`. For a teammate branch (held by the worktree) `push`
relocates: it detaches the main checkout onto the story tip, pushes (so the
hook runs with the main checkout's installed deps against the story's code),
then restores the main checkout to its base — reusing `accept-env`'s
Mechanism A. Solo branches (already checked out here) push directly. `--smm-dir`
lets the relocate resolve the base ref.

Stdout is `pushed: <branch>` or `skipped: no remote configured`.

## Step 3: PR creation

```bash
PR_OUTPUT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py create-pr \
  --cwd ${TEAMMATE_CWD:-.} --base <TARGET_BRANCH> --head <CURRENT_BRANCH> \
  --title "[<story-id>] <story title>" --body "<story summary + AC bullets>")
```

`PR_OUTPUT` is a PR number or `skipped: no gh on PATH`.

## Step 4: Security Review (skipped)

Skipped — sprint-close runs cumulative `/security-review` for all merged stories.

## Step 4.5: Review (routed by REVIEW_PATH)

Route on the preload's `REVIEW_PATH` — **do NOT evaluate cadence yourself**.
`close-reviewer` (commit cadence / default) → Step 4.5a; `full-cycle` (story
cadence) → Step 4.5b. Step 1b's file_domain drift surface runs in both.

### Step 4.5a: Fork the close-reviewer (REVIEW_PATH=close-reviewer)

Compute the diff command:

```bash
DIFF_CMD=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py diff-command \
  --target <TARGET_BRANCH> --source <CURRENT_BRANCH>)
```

Substitute the captured value as `<DIFF_CMD>` in the agent prompt below.

```
Agent(
  subagent_type: "xp-agents:xp-close-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\nSYSTEM_CONTEXT_RENDERED=<SYSTEM_CONTEXT_RENDERED>\n\n## Mode\nstory\n\n## Source Branch\n<CURRENT_BRANCH>\n\n## Target Branch\n<TARGET_BRANCH>\n\n## Diff Command\n<DIFF_CMD>\n\n## Close Cycle ID\n<CLOSE_CYCLE_ID>\n\n## Context\nClosing story branch <CURRENT_BRANCH> for story <story-id> into <TARGET_BRANCH>. PR <PR_OUTPUT or 'not created (no gh)'>.\n\n## Instructions\nRun the Diff Command, analyze cumulative diff with story-mode focus (AC alignment, file_domain enforcement against sprint.json, story-bounded scope creep, regression risk in unmodified stories). Return Keep / Concern / Block summary."
)
```

### Step 4.5b: Quality review (REVIEW_PATH=full-cycle)

Story cadence runs the review **here** (the merge), not per-commit. Run
`/xp-quality-review` on the **cumulative** diff (`<TARGET_BRANCH>...HEAD`), not a
staged diff:

- `/xp-quality-review` — its preload emits `MODE=self-find`, so the independent
  `xp-code-reviewer` self-finds correctness plus quality/drift/debt; fix findings
  inline (or record as debt with a reason), as in the per-commit flow. Supply
  `<CLOSE_CYCLE_ID>` when spawning it, tagging any blocking finding as a high concern.

Do not fork `xp-close-reviewer` here — the quality review subsumes it; the
broad multi-agent code review runs at sprint close. A blocking finding is
tagged as a high concern for condition 2 below to consume.

## Steps 5–6: Apply shared close-pipeline reference

The shared close-pipeline reference (Steps 5, 5b, 6) is emitted by the
preload — see `scripts/_close_pipeline_shared.md`. Apply in order after
Step 4.5, then continue with Step 7.

**Story-close override for Step 6 (auto-merge gate):** skip the shared
Step 6 `AskUserQuestion` and proceed to Step 7 when ALL hold:

1. Step 5c queued zero ask-user items, verified via:
   ```bash
   ASK_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
     --smm-dir <SMM_DIR> count-classifications \
     --route ask --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
   ```
   `<CLOSE_CYCLE_ID>` and `<CLOSE_START_TS>` come from the preload.
   `--cycle-id` scopes by close-cycle (SMM is shared across worktrees).
   Test `[ "$ASK_COUNT" -gt 0 ]` → fall through to shared Step 6.
2. No open high-severity concern recorded during Step 4.5:
   ```bash
   HIGH_CONCERN_COUNT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py \
     --smm-dir <SMM_DIR> count-concerns \
     --severity high --cycle-id <CLOSE_CYCLE_ID> --since-ts <CLOSE_START_TS>)
   ```
   Test `[ "$HIGH_CONCERN_COUNT" -gt 0 ]` → fall through to shared Step 6.
3. Preload emitted a non-empty `TEST_COMMAND=...` AND running it after
   all Step 5c fixes landed exits 0.

When `TEST_COMMAND` is empty, print this hint before falling through:

```
Auto-merge disabled — set stack.test_command in system_context.json to enable.
To set it, pipe the command (JSON-quoted) into the edit-stack-field CLI:
    printf %s '"<your-test-command>"' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> edit-stack-field test_command
```

When all three conditions hold, print:
"All reviewer findings addressed and tests green — proceeding to merge
without confirmation."
then continue to Step 7. Otherwise apply the shared Step 6 prompt.

## Step 7: Merge

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/close_common.py merge \
  --cwd . --source <CURRENT_BRANCH> --target <TARGET_BRANCH> \
  --verify-gate touch --review-clean-cwd "${TEAMMATE_CWD}" --smm-dir <SMM_DIR>
```

`--verify-gate touch` is a deterministic backstop: it re-derives the Step 1c
verify-touch check and refuses the merge if no commit touched the story's
declared acceptance-test paths (unless a `[verify-deferred]` commit defers).
Step 1c stays the first line of defense; this guards a skipped Step 1c.

`--review-clean-cwd "${TEAMMATE_CWD}"` is a second deterministic backstop for
the teammate path: a reviewer fix applied in Step 4.5b lands in the teammate
worktree, and Step 7b then removes that worktree — so an uncommitted fix would
be silently discarded. The merge refuses when `TEAMMATE_CWD` is a real worktree
that is dirty, so the lead either commits the reviewer's fix
(`git -C ${TEAMMATE_CWD} add -A && git -C ${TEAMMATE_CWD} commit -m ...` — `add
-A` also stages NEW files a `commit -am` would miss) or clears unrelated scratch
(`git -C ${TEAMMATE_CWD} stash -u`) first. Empty for solo closes (the working
tree persists, nothing to lose), and a missing/invalid `TEAMMATE_CWD` — the
check is skipped.

Always at orchestrator cwd (see intro). Any failing step aborts the
chain — source intact for retry. Conflicts are never auto-resolved.

## Step 7b: Teammate worktree cleanup (if applicable)

If the just-closed story was a teammate's, a `worktree-<story-id>`
worktree exists (out of the repo). Solo stories have no worktree
to clean up.

```bash
STORY_ID=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
  --smm-dir <SMM_DIR> extract-story-id --branch "<CURRENT_BRANCH>")
WORKTREE_NAME=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
  --smm-dir <SMM_DIR> find-teammate-worktree \
  --story-id "$STORY_ID" --cwd .)

if [ -n "$WORKTREE_NAME" ]; then
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup_teammate.py \
    --name "$WORKTREE_NAME" --smm-dir <SMM_DIR>
fi
```

## Reporting Back

**Surface the merge's trailer advisory.** The merge step's `close_common.py merge` prints a `Resolves-Event:` trailer advisory to stdout when eligible commits fall below the trailer target (fail-open — it never blocks the merge). Tool output is invisible to the user, so if the merge printed that advisory, relay it verbatim — the named commits are still in reach to add trailers.

Tell the user: story branch merged into sprint, PR (if created)
merged, local branch deleted. Close stops here — it does NOT promote
or branch the next story. `/xp-accept`'s post-loop owns the next
dispatch: it invokes `/xp-schedule` (the sole owner of
`scheduled → in-progress`) to promote + mode-select the next frontier
off the merged tip, or dispatches sprint review when none remain.
