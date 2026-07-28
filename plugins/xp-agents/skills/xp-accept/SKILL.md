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

> **Sequential discipline.** The harness batches independent tool calls in
> parallel; this skill is step-gated. Run Step 1 → 1.0 → 1b → 1.5 → 2 → 3 → 4 →
> 5 → 6 → 7 → 8 strictly, one step per turn — make the call, observe, then decide
> the next. Never put an `AskUserQuestion` and the action consuming its answer in
> one block (the Step 1 accept/defer question vs the `/xp-story-close` call in
> Step 2); never spawn the same subagent twice. Independent read-only calls may
> still batch.

The preload shows: count of stories under acceptance,
`SELECTED_STATUS=reviewing|in-progress`, `SPRINT_FILE=<path>`, or
ERROR/NO_STORIES_TO_ACCEPT. Reviewing-first dispatch picks `reviewing`
stories when present (teammate self-promote path), else `in-progress`
(solo path) — iterate whichever set was selected.

**If ERROR or NO_STORIES_TO_ACCEPT**, explain and stop.

If the preload shows a **TEAMMATE_WORKTREES** section, each row is
`story-id<TAB>abs-path<TAB>tip-sha<TAB>restore-ref` (literal tab —
split on tab, not space; paths may contain spaces). Teammate branches
are NOT merged yet (per-story merge is `/xp-story-close`'s job in
Step 2). Teammate-story acceptance runs **serially in the provisioned
main checkout**, detached onto the story's tip via `accept-env`
(prepare → run → restore) — never by `cd`-ing into the teammate
worktree, which has the code but no installed deps. A trailing
`MAIN_STATE<TAB><in-progress-merge|detached-HEAD|dirty>` line flags a
main checkout that needs recovery before any checkout (Step 1's
precondition below handles it).

**Pipeline precedence, before draining this loop.** A task-notification
lands here, at the top of the accept loop — not at some later handoff.
Before working the selected set below, check whether any story is
planned, reviewed and un-spawned: if so, hand off to `/xp-assign` to
spawn it first, then return here to accept. If there is nothing left to
spawn, accept immediately — the rule is precedence, not a reason to
delay acceptance. Draining every `reviewing` story before checking for
spawnable work leaves the background empty for the whole close cycle.

## Step 1: Review Each Story Under Acceptance

Read the sprint file at `SPRINT_FILE`. For each story in the selected set
(reviewing or in-progress per `SELECTED_STATUS`), check its
`acceptance_execution` field (the preload's `### Acceptance Types`
section shows each story's routing for quick reference).

### Precondition: heal the main checkout

If the preload shows a `MAIN_STATE` line (under `### TEAMMATE_WORKTREES`),
heal the main checkout before any `accept-env prepare` — gate on the flag, not
teammate-vs-solo (a leftover interrupted state surfaces even with no live worktree):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  accept-env recover --cwd .
```

`recover` aborts an interrupted merge / detached HEAD and restores the
base. If the tree is still **dirty** (or `MAIN_STATE` was `dirty`),
**refuse** — do not checkout. No `MAIN_STATE` line → nothing to heal, skip.

### Step 1.0: Promote to `reviewing` (idempotent)

Before running the acceptance command, promote the story to `reviewing`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN reviewing
```

The promote is **idempotent** — no-op when `SELECTED_STATUS=reviewing`
(teammate self-promoted), real transition when `in-progress` (solo).
Fix-cycle Edits during the `reviewing`/`closing` window don't re-arm the
`.accept` marker.

If acceptance fails and the user picks **Debug and re-run**, revert to
`in-progress` before fixing — the story is actively-worked again (applies
from `reviewing` OR Step 1.5's `closing`, skipping the middle state):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN in-progress
```

### Automated acceptance (acceptance_execution carries a command)

Route on **command presence**, not `type`: when `acceptance_execution` carries
a `command`/`commands` — **including a `type: "manual"` block** — run the
prepare → run → restore → disposition flow below via
`verify_acceptance.py --story <id>` (the single runner; per story-021 it runs a
manual block's command and N/As a command-less one).

**Present.** Show the story title and acceptance criteria.

**Prepare.** **Teammate story (id in TEAMMATE_WORKTREES):** detach the
main checkout onto the story's tip and capture the restore ref
(`accept-env prepare`); for a **solo** story (no worktree), skip
prepare/restore and run bare from the main repo.

```bash
RESTORE_REF=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py \
  --smm-dir <SMM_DIR> accept-env prepare --cwd . --story story-NNN)
```

**Run.** Run `acceptance_execution.setup` (if present), then the check via
`verify_acceptance.py --story <id> --smm-dir <SMM_DIR>` **bare in the
main-checkout cwd** — no `cd`-into-worktree wrap. It runs `command`/`commands`
in order (fail on first non-zero). Capture the exit code.

**Restore on every exit path** — pass OR fail, before the disposition
branch and any `AskUserQuestion` (solo: nothing to restore). The
checkout is ephemeral; the permanent merge is in `/xp-story-close`.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  accept-env restore --cwd . --restore-ref "$RESTORE_REF"
```

**Pass.** **Exit code 0 = pass. Auto-proceed to Step 2 without an extra
confirmation prompt** — the green exit IS the confirmation, and
`/xp-story-close` owns merge confirmation.

**Fail.** **Non-zero exit = fail.** Show the output and ask via
`AskUserQuestion` with three options: **Debug and re-run**,
**Override with concern**, **Defer**.

**Debug and re-run.** **Restore** already returned the main checkout to
the base, so you are NOT on the detached tip — never commit a fix there
(orphaned on restore). Revert to `in-progress` (Step 1.0's revert), then
fix in the teammate **worktree**, committing from the orchestrator with
`git -C <literal-worktree-path> commit ...` — never `cd <worktree> && git
commit && cd -` (the cd-back fires before the PostToolUse trailer-extract
hook reads HEAD, breaking `Resolves-Event:` auto-links). An unresolvable
`-C` is refused. If invoking
`/xp-quality-review`, set `TEAMMATE_CWD=<worktree-path>`. Then
**re-prepare** (loop to prepare) — the new tip has the fix.

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

### Manual walkthrough (no runnable command)

Reserved for a block with **no runnable command**: no `acceptance_execution`,
or a `type: "manual"` block carrying only `steps`/prose (one with a command
took the automated path).

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
- Auto-resolve MAYBE ADDRESSED concerns
- Confirm and run `close_common.py merge`

Close stops at the merge — it does NOT promote or branch the next
story. The next-frontier promotion is owned by Step 8's post-loop
dispatch (the sole owner of `scheduled → in-progress`).

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

Present: how many stories marked done, how many deferred (per-story
teammate-worktree cleanup is owned by /xp-story-close Step 2).

The `ACCEPT_IN_FLIGHT` suppression marker is consumed automatically by a hook
at accept's terminal handoff (the next-story scheduling or the sprint review) —
no prose consume step; the SessionStart sweep is the abandonment backstop.

## Step 7: Sprint Review

Read the deterministic completeness signal — the sprint is complete only when
NO story is in an active status (every story `done` or `deferred`). A drained
teammate batch with in-progress work, or leftover `scheduled`/`ready` stories,
is NOT complete — so do not eyeball "all done or deferred", read the signal:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> is-complete
```

Exit 0 = complete → run `/xp-sprint-review` immediately (do not wait for the
stop gate). Exit 1 = not complete → continue to Step 8.

## Step 8: Continue to next story

Reached only when Step 7's `is-complete` returned NOT complete. Run
`/xp-schedule` ONCE (single dispatch per accept run) — the sole owner of
`scheduled → in-progress`. It promotes the next frontier, sets each story's
execution_mode, and (solo) JIT-creates the branch off the merged sprint tip;
then follow its handoff into the plan cycle (enter plan mode →
`/xp-review-plan` → teammate-mode `/xp-assign`).

If `/xp-schedule` reports no ready frontier (`FRONTIER_COUNT 0`), do **not**
infer the sprint is complete — Step 7's `is-complete` already ruled that out.
A 0 frontier here means work remains that is not yet promotable: in-progress/
reviewing/closing stories still draining, `scheduled` stories blocked on
unfinished deps, or `ready` stories not yet selected. Report what remains
(e.g. "N stories in-progress, M ready — continue the in-progress work, or run
`/xp-work-selection` to pull ready stories") and stop **without** firing
`/xp-sprint-review`.
