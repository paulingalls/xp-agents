---
name: xp-accept
description: >-
  Verify acceptance criteria for in-progress stories. Present criteria,
  guide e2e test execution, mark stories done or deferred, update sprint.json.
allowed-tools:
  - Read
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Accept Verification

The preload above shows the sprint state: in-progress count + `SPRINT_FILE=<path>`, or ERROR/NO_IN_PROGRESS.

**If the preload shows "ERROR" or "NO_IN_PROGRESS"**, explain the situation and stop. There is nothing to accept.

## Step 0: Cross-Teammate Review (if TEAMMATE_WORKTREES shown)

If the preload shows **TEAMMATE_WORKTREES**, teammate branches were merged into the current branch. Run a cross-teammate review cycle on the merged code to catch inter-story issues:

1. Run `/simplify` scoped to the merged teammate changes — use `Skill(skill: "simplify", args: "the merged teammate changes since before the teammate merges")` so the review covers the merge diffs, not the empty working tree
2. Run `/xp-quality-review` — check for drift against SMM constraints and inter-story debt
3. Run `/security-review` scoped to the merged teammate changes — use `Skill(skill: "security-review", args: "the merged teammate changes since before the teammate merges")` so the review covers the merge diffs, not the entire branch history

This catches issues that individual teammate reviews might miss (e.g., duplicated patterns across stories, conflicting approaches, or combined security implications).

If no TEAMMATE_WORKTREES section is shown, skip to Step 1.

## Step 1: Review Each In-Progress Story

Read the sprint file using the `SPRINT_FILE` path from the preload output. For each story with `**Status:** in-progress`:

1. **Present the story** — show the story title and all acceptance criteria.
2. **For each E2E criterion** (prefixed with "E2E:") — guide the user to run the test. Use Bash to execute test commands if the criterion specifies them. Report results.
3. **For non-E2E criteria** — ask the user to verify each criterion is met.
4. **Ask the user** via `AskUserQuestion`: "Mark **story-NNN** as `done` or `deferred`?"
   - **done** — all acceptance criteria verified and passing
   - **deferred** — story is incomplete, carry forward to next sprint
5. If the user has questions or wants to discuss, resolve inline before marking.

## Step 2: Update sprint.json

The accept gate marker was already cleared by the preload script. Update each story's status via CLI:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN done
```

Or for deferred stories:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN deferred
```

## Step 3: Record Events

For each story disposition, record a status event:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-accept" \
  --content "Story story-NNN marked <done|deferred>: <brief reason>" \
  --working-on '[]'
```

## Step 4: Summary

Present a summary: how many stories marked done, how many deferred.

## Step 5: Cleanup Teammate Worktrees (if TEAMMATE_WORKTREES shown)

If the preload showed **TEAMMATE_WORKTREES**, clean up each accepted story's worktree:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup_teammate.py \
  --name teammate-story-NNN --smm-dir <SMM_DIR>
```

The script verifies the branch is merged before removing the worktree, branch, agent markers, and report file. Only clean up worktrees for stories marked **done** — leave deferred story worktrees intact for re-entry.

If cleanup fails (unmerged commits), report the error and skip that worktree.

## Step 6: Sprint Review

**If all stories are now done or deferred**, the sprint is complete. Run `/xp-sprint-review` immediately — do not wait for the stop gate to catch it. The sprint review records velocity, updates the execution plan, and triggers sizing metrics for the next retrospective.
