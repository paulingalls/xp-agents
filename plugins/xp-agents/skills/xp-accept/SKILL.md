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
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Accept Verification

The preload shows: count of stories under acceptance,
`SELECTED_STATUS=reviewing|in-progress`, `SPRINT_FILE=<path>`, or
ERROR/NO_STORIES_TO_ACCEPT. Reviewing-first dispatch picks `reviewing`
stories when present (teammate self-promote path), else `in-progress`
(solo path) — iterate whichever set was selected.

**If ERROR or NO_STORIES_TO_ACCEPT**, explain and stop.

If the preload shows a **TEAMMATE_WORKTREES** section, each row is
`story-id<TAB>abs-path` (literal tab — split on tab, not space; paths
may contain spaces). Teammate branches are NOT merged yet (per-story
merge is `/xp-story-close`'s job in Step 2). Use the path to `cd` into
each story's worktree when running its acceptance command — unmerged
teammate edits live there, not in the orchestrator's HEAD.

## Step 1: Review Each Story Under Acceptance

Read the sprint file at `SPRINT_FILE`. For each story in the selected set
(reviewing or in-progress per `SELECTED_STATUS`), check its
`acceptance_execution` field (the preload's `### Acceptance Types`
section shows the type per story for quick reference).

### Step 1.0: Promote to `reviewing` (idempotent)

Before running the acceptance command, promote the story to `reviewing`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN reviewing
```

The promote is **idempotent** — no-op when `SELECTED_STATUS=reviewing`
(teammate self-promoted), real transition when `in-progress` (solo).
`pre_tool_write`'s `.accept`-marker re-arm predicate skips while a
story is in `reviewing` OR `closing`, so fix-cycle Edits during the
acceptance/close window don't re-arm the marker.

If acceptance fails and the user picks **Debug and re-run**, revert
before fixing — the story is actively-worked again:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN in-progress
```

The same revert command applies if acceptance fails after Step 1.5's
reviewing→closing transition: `closing → in-progress` skips the
reviewing middle state.

### Automated acceptance (type != "manual")

When `acceptance_execution` is present and `type` is not `"manual"`:

1. Present the story title and acceptance criteria.
2. If `acceptance_execution.setup` is present, run it first via Bash.
3. Run the acceptance command(s) via Bash. Schema accepts
   `acceptance_execution.command: str` OR `commands: list[str]` (run
   in order, fail on first non-zero). For multi-command, prefer
   `verify_acceptance.py --story <story-id> --smm-dir <SMM_DIR>` which
   handles iteration, first-red exit, and failing-command stderr.
   If the story's id appears in TEAMMATE_WORKTREES, wrap in a subshell
   so cwd doesn't persist: `(cd <abs-path> && <command>)`. Otherwise
   run bare from the main repo.
4. **Exit code 0 = pass. Auto-proceed to Step 2 without an extra
   confirmation prompt** — the green exit IS the confirmation, and
   `/xp-story-close` owns merge confirmation.
5. **Non-zero exit = fail.** Show the output and ask via
   `AskUserQuestion` with three options: **Debug and re-run**,
   **Override with concern**, **Defer**.

**Debug and re-run.** Revert to `in-progress` (Step 1.0's revert
command), fix, re-run. When the fix lands in a teammate worktree
(story-id in TEAMMATE_WORKTREES), commit from the orchestrator with
`git -C <worktree-path> commit ...` — never
`cd <worktree> && git commit && cd -` (the cd-back fires before the
PostToolUse trailer-extract hook reads HEAD, silently breaking
`Resolves-Event:` auto-links). If invoking `/xp-quality-review`, set
`TEAMMATE_CWD=<worktree-path>` so QR's diff/debt scan routes to the
worktree.

**Override with concern.** Mark as passing despite failure. Records a
`concern` event with the story's `file_domain` for structural
commit-link matching:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "xp-accept" --severity "medium" \
  --content "Acceptance override for story-NNN: <user's reason>" \
  --files '["<story-NNN file_domain entries>"]'
```

**Defer.** Move to `deferred`. If the story has downstream dependents,
cascade the deferral (see "Cascading a deferral").

Do **not** retry automatically. Flaky acceptance is information.

### Manual acceptance (type = "manual" or no acceptance_execution)

1. Present the story title and all acceptance criteria.
2. For each **E2E criterion** (prefixed "E2E:") — run the test via Bash; report results.
3. For non-E2E criteria — ask the user to verify.
4. **If every criterion is E2E-prefixed and all exited 0**, skip the
   prompt and proceed to Step 1.5 with disposition `done` — the green
   exits ARE the confirmation. **Otherwise**, ask via `AskUserQuestion`:
   "Mark **story-NNN** as `done` or `deferred`?"
   - **done** — all criteria verified and passing.
   - **deferred** — incomplete; cascade if there are downstream
     dependents (see "Cascading a deferral").

Manual flow has no debug-and-fix branch — pick `deferred` to revisit
later. The story stays in `reviewing` through Step 1b, then `closing`
through Step 4. If review is abandoned without picking, revert to
`in-progress` via `update-story story-NNN in-progress`.

### Cascading a deferral

When a deferred story has in-motion (in-progress/reviewing/closing)
downstream dependents, mark them deferred too — running on a broken
base wastes cycles.

```bash
DEFERRED="story-NNN"

CASCADE=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  find-transitive-dependents "$DEFERRED")

for sid in "$DEFERRED" $CASCADE; do
  python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
    update-story "$sid" deferred
done
```

Step 5 records a status event per deferral with the cascade reason.

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

## Step 1.5: Transition reviewing → closing (CAS-guarded)

Immediately before dispatching /xp-story-close, transition the story
from `reviewing` to `closing`. `closing` is the singleton in-pipeline
lock — exactly one story inside /xp-story-close at a time, while
`reviewing` stays plural-safe for concurrent teammate finish-bursts.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story-if story-NNN --expected reviewing --new closing
```

`update-story-if` is a compare-and-swap: rc=0 success, rc=1 when the
story is no longer at `reviewing` (already advanced — skip and continue
to the next story), rc=2 on validation errors (halt and surface
stderr — rc=2 means corrupt sprint.json, not a benign race).

## Step 2: Invoke /xp-story-close (close-then-done)

**Close FIRST, then mark done.** The story sits in `closing`
throughout the close cycle (Step 1.5 → Step 4); mark-done (Step 4) is
the FINAL step, after /xp-story-close success and Step 3 decisions.

/xp-story-close auto-discovers teammate worktree state — no context-
passing from /xp-accept needed — and owns:

- Fork `xp-close-reviewer` (story mode: AC, file_domain, scope creep,
  regression risk)
- Auto-resolve LIKELY ADDRESSED concerns
- Confirm and run `close_common.py merge`
- (Solo) JIT-create the next scheduled story's branch off the merged tip

**Merge-failure semantics:** on abort (preflight fails, reviewer Block,
user picks abort, merge conflicts) the story stays in `closing`;
Step 4 never runs, retry is safe. Use Step 1's debug-and-rerun
(`closing → in-progress`) when fixing and re-ACing.

**Stage 0:** orchestrator commits directly on the primary branch, so
preflight refuses (CURRENT_BRANCH IS TARGET_BRANCH). Skip Step 2 at
stage 0; proceed directly to Step 3 then Step 4.

Loop continues for the next reviewing story. /xp-story-close NEVER
fires /xp-sprint-review — Step 7 below owns that single dispatch.

## Step 3: Record design decisions for the story

After Step 2 success and BEFORE Step 4, record qualifying design
decisions while the close-review context is fresh. Qualifying shapes:
chose X over Y for reason Z, rejected A for B, defined a contract/
boundary, accepted a known tradeoff. Does NOT qualify: variable names,
local refactor sequences, lint-driven cleanups.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "xp-accept" \
  --topic "<short-slug>" \
  --content "<one-sentence statement of the decision and its rationale>"
```

If no decision qualifies, record the explicit zero so retros can
distinguish ran-and-found-none from skipped:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-accept" \
  --content "story-NNN: no design decisions to record" \
  --working-on '[]'
```

## Step 4: Update sprint.json (after successful close + decisions)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN <done|deferred>
```

`done` only runs AFTER Step 2 success and Step 3 decisions. `deferred`
runs without a preceding close (branch stays intact for next sprint).

## Step 5: Record Events

For each story disposition (including cascaded deferrals from Step 1):
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-accept" \
  --content "Story story-NNN marked <done|deferred>: <brief reason>" \
  --working-on '[]'
```

For cascaded deferrals, include the cascade reason (e.g., "deferred: depends on deferred story-MMM").

## Step 6: Summary

Present: how many stories marked done, how many deferred. Per-story
teammate-worktree cleanup is owned by /xp-story-close (Step 2).

## Step 7: Sprint Review

**If all stories are now done or deferred**, the sprint is complete. Run `/xp-sprint-review` immediately — do not wait for the stop gate.

## Step 8: Continue to next story

If Step 7 did not fire, run:

```bash
NEXT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> next-in-progress)
```

If `NEXT` is non-empty (rc=0 — a fresh JIT-promote from
`/xp-story-close`), call the `EnterPlanMode` tool (no args; the new
story is the planning subject) so the plan cycle starts immediately
on the next iteration. If `NEXT` is empty (rc=1), no further work —
stop.
