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

The preload above shows sprint state: in-progress count + `SPRINT_FILE=<path>`, or ERROR/NO_IN_PROGRESS.

**If ERROR or NO_IN_PROGRESS**, explain and stop.

## Step 0: Cross-Teammate Review (if TEAMMATE_WORKTREES shown)

If the preload shows **TEAMMATE_WORKTREES**, teammate branches were merged. Run a cross-teammate review cycle on the merged code:

1. `/simplify` scoped to merged teammate changes (use `args: "the merged teammate changes since before the teammate merges"`)
2. `/xp-quality-review` — check for drift and inter-story debt
3. `/security-review` scoped to merged teammate changes (use `args: "the merged teammate changes since before the teammate merges"`)

Skip if no TEAMMATE_WORKTREES section.

## Step 1: Review Each In-Progress Story

Read the sprint file at `SPRINT_FILE`. For each in-progress story:

1. Present the story title and all acceptance criteria
2. For each **E2E criterion** (prefixed "E2E:") — run the test via Bash. Report results.
3. For **non-E2E criteria** — ask the user to verify
4. Ask via `AskUserQuestion`: "Mark **story-NNN** as `done` or `deferred`?"
   - **done** — all acceptance criteria verified and passing
   - **deferred** — incomplete, carry forward to next sprint
5. Resolve any user questions before marking

## Step 2: Update sprint.json

Update each story's status via CLI:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN <done|deferred>
```

## Step 3: Record Events

For each story disposition:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-accept" \
  --content "Story story-NNN marked <done|deferred>: <brief reason>" \
  --working-on '[]'
```

## Step 4: Summary

Present: how many stories marked done, how many deferred.

## Step 5: Cleanup Teammate Worktrees (if TEAMMATE_WORKTREES shown)

For each **done** story's worktree:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup_teammate.py \
  --name teammate-story-NNN --smm-dir <SMM_DIR>
```

Verifies branch is merged before removing worktree, branch, markers, and report. **Only cleanup done stories** — leave deferred worktrees intact. If cleanup fails (unmerged commits), report and skip.

## Step 6: Sprint Review

**If all stories are now done or deferred**, the sprint is complete. Run `/xp-sprint-review` immediately — do not wait for the stop gate.
