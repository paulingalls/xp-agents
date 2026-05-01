---
name: xp-accept
description: >-
  Verify acceptance criteria for in-progress stories. Present criteria,
  guide e2e test execution, mark stories done or deferred, update sprint.json.
allowed-tools:
  - Read
  - Bash
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Skill
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Accept Verification

The preload above shows sprint state: in-progress count + `SPRINT_FILE=<path>`, or ERROR/NO_IN_PROGRESS. The preload also auto-consumes the `.accept` marker (the ACCEPT gate that blocks `update-story done` between sessions) — you do not need to clear it manually; the gate is already open by the time you read this.

**If ERROR or NO_IN_PROGRESS**, explain and stop.

If the preload shows a **TEAMMATE_WORKTREES** section, each row is
`story-id: abs-path`. Teammate branches are NOT merged at this point
(per-story merge is `/xp-story-close`'s job, dispatched in Step 2b
below). Use the path to `cd` into each story's worktree when running
its acceptance command in Step 1 — the unmerged teammate edits live
there, not in the orchestrator's HEAD.

Cross-teammate review is layered: per-story `/xp-story-close` close-
reviewer (Read access to merged-in siblings) + project pre-commit
hook on every merge + `/xp-sprint-close` cumulative review at sprint
boundary. No separate cross-teammate dispatch at /xp-accept time.

## Step 1: Review Each In-Progress Story

Read the sprint file at `SPRINT_FILE`. For each in-progress story, check its `acceptance_execution` field (the preload's `### Acceptance Types` section shows the type per story for quick reference):

### Automated acceptance (type != "manual")

When `acceptance_execution` is present and `type` is not `"manual"`:

1. Present the story title and acceptance criteria.
2. If `acceptance_execution.setup` is present, run it first via Bash.
3. Run `acceptance_execution.command` via Bash. If the story's
   `story-id` appears in TEAMMATE_WORKTREES, set the Bash `cwd` to
   that worktree's `abs-path`; otherwise run from the main repo.
   Universal pattern — works regardless of test runner (pytest,
   jest, go test, cargo test).
4. **Exit code 0 = pass.** Report success, proceed to mark done.
5. **Non-zero exit = fail.** Show the output and ask via `AskUserQuestion`:
   - **Debug and re-run** — investigate the failure, fix the cause, then re-run the command
   - **Override with concern** — mark as passing despite failure. Requires a reason string. Records a `concern` event:
     ```bash
     ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
       --type "concern" --agent "xp-accept" --severity "medium" \
       --content "Acceptance override for story-NNN: <user's reason>"
     ```
   - **Defer** — move story to `deferred` with a reason. **If the story has downstream dependents** (other in-progress stories whose `dependencies` include it, directly or transitively), cascade the deferral: defer the failed story AND all downstream dependents. Step 3 records status events for each cascaded deferral.

Do **not** retry automatically. Flaky acceptance is information — fix the harness, don't mask the signal.

### Manual acceptance (type = "manual" or no acceptance_execution)

When `acceptance_execution` is absent or `type` is `"manual"`:

1. Present the story title and all acceptance criteria.
2. For each **E2E criterion** (prefixed "E2E:") — run the test via Bash. Report results.
3. For **non-E2E criteria** — ask the user to verify.
4. Ask via `AskUserQuestion`: "Mark **story-NNN** as `done` or `deferred`?"
   - **done** — all acceptance criteria verified and passing
   - **deferred** — incomplete, carry forward to next sprint. **If the story has downstream dependents** (other in-progress stories whose `dependencies` include it, directly or transitively), cascade the deferral: defer the failed story AND all downstream dependents. Step 3 records status events for each cascaded deferral.
5. Resolve any user questions before marking.

## Step 1b: Concern Triage

If the preload shows `### Concerns for story-NNN`, review each listed concern against the story's work. For each concern, judge whether the story's commits address it:

- **If clearly addressed** — resolve it:
  ```bash
  ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
    --type "status" --agent "xp-accept" \
    --content "Story story-NNN addresses concern: <brief reason>" \
    --working-on '[]' --metadata '{"resolves": ["<concern-id>"]}'
  ```
- **If unsure** — leave it open for manual triage at next work-selection.

File overlap alone does not mean a concern is resolved. Use your judgment based on the concern's content and what the commits actually changed.

## Step 2: Update sprint.json

Update each story's status via CLI:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN <done|deferred>
```

## Step 2b: Invoke /xp-story-close per done story

For each story just marked **done** (skip deferred — their branches
stay intact for the next sprint), invoke `/xp-story-close` via the
Skill tool. /xp-story-close owns the per-story review + merge +
JIT-create-next pipeline:

- Forks `xp-close-reviewer` in story mode (AC alignment, file_domain,
  scope creep, regression risk in unmodified stories)
- Auto-resolves LIKELY ADDRESSED concerns
- Asks the user to confirm the merge
- Runs `close_common.py merge` (chained merge --no-ff + push target +
  delete source — same pipeline used by sprint/plan/free-close)
- (Solo mode) JIT-creates the next in-progress story's branch off
  the merged sprint tip and checks it out

Loop continues for the next done story (each gets its own
/xp-story-close invocation). /xp-story-close NEVER fires
/xp-sprint-review — Step 6 below owns that single dispatch after
the loop completes (decision e30e9e91e61a).

**Stage 0:** at stage 0 there is no branch discipline — the
orchestrator commits directly on the primary branch — so
/xp-story-close's preflight will refuse (CURRENT_BRANCH IS
TARGET_BRANCH) and stop with a clear stderr message. Skip the
dispatch entirely at stage 0.

## Step 3: Record Events

For each story disposition (including cascaded deferrals from Step 1):
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-accept" \
  --content "Story story-NNN marked <done|deferred>: <brief reason>" \
  --working-on '[]'
```

For cascaded deferrals, include the cascade reason (e.g., "deferred: depends on deferred story-MMM").

## Step 4: Summary

Present: how many stories marked done, how many deferred.

Per-story teammate-worktree cleanup is owned by /xp-story-close
(invoked in Step 2b above) — it removes the teammate worktree per
closed story when one existed (decision 9029c07ae198).

## Step 5: Sprint Review

**If all stories are now done or deferred**, the sprint is complete. Run `/xp-sprint-review` immediately — do not wait for the stop gate.
