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

Read the sprint file at `SPRINT_FILE`. For each in-progress story, check its `acceptance_execution` field (the preload's `### Acceptance Types` section shows the type per story for quick reference).

### Step 1.0: Promote to `reviewing`

Before running the story's acceptance command, promote it from `in-progress` to `reviewing`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN reviewing
```

**Why this matters.** The 5-state lifecycle (`ready → scheduled → in-progress → reviewing → done/deferred`) carves the story out of `has_in_progress_stories` while it's under acceptance. `pre_tool_write` then does NOT re-arm the `.accept` marker on Edits during fix-cycles inside `/xp-story-close`, so the subsequent `update-story story-NNN done` is not blocked. This is the fix for the marker re-arm bug; the per-story promote is the trigger.

If acceptance later fails and the user picks **Debug and re-run** (Step 1's automated-fail branch), revert the promotion before fixing — the story is no longer under review, it's actively-worked again:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN in-progress
```

### Automated acceptance (type != "manual")

When `acceptance_execution` is present and `type` is not `"manual"`:

1. Present the story title and acceptance criteria.
2. If `acceptance_execution.setup` is present, run it first via Bash.
3. Run `acceptance_execution.command` via Bash. If the story's
   `story-id` appears in TEAMMATE_WORKTREES, wrap the command in a
   subshell so the parent shell's cwd does NOT persist into
   subsequent Bash calls: `(cd <abs-path> && <command>)`. Otherwise
   run the bare command from the main repo. The subshell isolates
   the cwd change to that one invocation — without it, a later Bash
   call inherits the worktree cwd and can mislead about branch
   state. Universal pattern — works regardless of test runner
   (pytest, jest, go test, cargo test).
4. **Exit code 0 = pass. Auto-proceed to Step 2 (update sprint.json) without calling `AskUserQuestion`.** The green exit code IS the confirmation. Do **not** insert an extra "mark story-NNN done?" prompt for automated acceptance — `/xp-story-close` owns merge confirmation (per Step 2b), so the user still gets a gate before the merge lands. This rule applies only to the automated-acceptance branch; manual acceptance below still prompts for `done | deferred` because there's no objective signal.
5. **Non-zero exit = fail.** Show the output and ask via `AskUserQuestion`:
   - **Debug and re-run** — revert the story to `in-progress` (per Step 1.0's revert command), investigate the failure, fix the cause, then re-run the command. The revert lets `pre_tool_write` re-arm the `.accept` marker on subsequent fix-cycle Edits.
   - **Override with concern** — mark as passing despite failure. Requires a reason string. Records a `concern` event:
     ```bash
     ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
       --type "concern" --agent "xp-accept" --severity "medium" \
       --content "Acceptance override for story-NNN: <user's reason>" \
       --files '["<story-NNN file_domain entries>"]'
     ```
     Pass the story's `file_domain` entries via `--files` so the structural commit-link probe can match future fixes to this concern.
   - **Defer** — move story to `deferred` with a reason. **If the story has downstream dependents** (other in-progress stories whose `dependencies` include it, directly or transitively), cascade the deferral — see "Cascading a deferral" below for the mechanics.

Do **not** retry automatically. Flaky acceptance is information — fix the harness, don't mask the signal.

### Manual acceptance (type = "manual" or no acceptance_execution)

When `acceptance_execution` is absent or `type` is `"manual"`:

1. Present the story title and all acceptance criteria.
2. For each **E2E criterion** (prefixed "E2E:") — run the test via Bash. Report results.
3. For **non-E2E criteria** — ask the user to verify.
4. Ask via `AskUserQuestion`: "Mark **story-NNN** as `done` or `deferred`?"
   - **done** — all acceptance criteria verified and passing
   - **deferred** — incomplete, carry forward to next sprint. **If the story has downstream dependents** (other in-progress stories whose `dependencies` include it, directly or transitively), cascade the deferral — see "Cascading a deferral" below for the mechanics.
5. Resolve any user questions before marking.

**Manual flow has no debug-and-fix branch.** If the user wants to fix issues mid-acceptance, pick `deferred` and revisit in a future iteration. The story stays in `reviewing` only briefly between Step 1.0's promote and the `done`/`deferred` mark; if neither is chosen, manually revert to `in-progress` via `update-story story-NNN in-progress` so subsequent Edits re-arm the `.accept` marker.

### Cascading a deferral

When a deferred story has in-motion (in-progress or reviewing) downstream dependents, mark them deferred too — running them on the (now-broken) base would waste cycles. `sprint_cli.py find-transitive-dependents` walks `sprint.json` and prints the descendants; loop `update-story` over the failed story plus that list:

```bash
DEFERRED="story-NNN"  # the just-deferred story id

CASCADE=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  find-transitive-dependents "$DEFERRED")

for sid in "$DEFERRED" $CASCADE; do
  python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
    update-story "$sid" deferred
done
```

Step 3 records a status event for each deferral with the cascade reason (e.g., "deferred: depends on deferred story-NNN").

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

## Step 1c: Tier 2 Security Review

Tier 2 security gate: fire `/security-review` against the cumulative story diff before marking the story done.

**Skip when the story is `code_free`** (empty `file_domain` — verification-only / prose-only). The cumulative diff has no code worth reviewing.

**Scope distinct from Step 0.** Step 0 covers the teammate-merge slice only; Step 1c covers the full cumulative story diff (`git merge-base <story-branch> <sprint-base>` ... HEAD). Both run when both apply — overlap is tolerated. Always name the cumulative-merge-base scope in the args string so the LLM does not silently reuse Step 0's scope.

For the current story (skip if code_free):

1. Invoke `Skill(skill: "security-review", args: "<scope>")` where `<scope>` is a concrete sentence naming THIS story's branch and the sprint base — substitute the actual branch names, do not pass the literal placeholders. Example: `args: "the cumulative diff for story-007 on branch paulingalls/story-007-perf-consolidation since merge-base with paulingalls/sprint-049-tier2-accept-security"`. The PostToolUse:Skill hook auto-emits a `security_complete` status event.
2. Read the prose findings and judge severity per the close-reviewer convention (see `agents/xp-close-reviewer.md` "Step 4: Record Concerns as SMM Events"): **Block = high**, **Concern = medium**, **Keep = no event**.

**Block path** (high-severity findings): **do NOT call `sprint_cli.py update-story story-NNN done`.** Present via `AskUserQuestion`:

- **Defer** — move story to `deferred` (cascade downstream dependents same as Step 1):
  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
    update-story story-NNN deferred
  ```
- **Override with concern** — proceed to update-story done despite the Block. Record both a severity-high concern (so the risk stays visible) AND a decision event (so the architectural choice to ship despite the Block is captured for future retros):
  ```bash
  ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
    --type "concern" --agent "xp-accept" --severity "high" \
    --content "Tier 2 Block override for story-NNN: <one-line summary>" \
    --files '["<paths /security-review pointed at>"]'

  ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
    --type "decision" --agent "xp-accept" \
    --topic "tier-2-block-override-story-NNN" \
    --content "Accepted Tier 2 Block for story-NNN: <one-line rationale — what risk we knowingly took and why it's acceptable now>"
  ```

**Concern path** (medium-severity findings, no Block): record each finding, then proceed to update-story done:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "xp-accept" --severity "medium" \
  --content "Tier 2 finding for story-NNN: <one-line summary>" \
  --files '["<paths /security-review pointed at>"]'
```

For both paths: pass the file paths /security-review named (or the story's `file_domain` if the finding is broader). Concerns without `files=[]` cannot auto-resolve when the eventual fix lands.

**Keep path** (no findings): proceed to Step 2.

## Step 2: Update sprint.json

Update each story's status via CLI:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
  update-story story-NNN <done|deferred>
```

## Step 2b: Per-done-story actions

For each story just marked **done** (skip deferred — their branches
stay intact for the next sprint), perform 2b.i then 2b.ii in order.

### Step 2b.i: Record design decisions for the story

**Criterion:** A "design decision" at story scope is anything another
agent (or future-you in a retro) would need to know to avoid making a
*conflicting* choice. Qualifying shapes: chose X over Y for reason Z,
rejected A for B, defined a contract/boundary, accepted a known
tradeoff. Does NOT qualify: variable names, local refactor sequences,
lint-driven cleanups.

For each qualifying decision:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "xp-accept" \
  --topic "<short-slug>" \
  --content "<one-sentence statement of the decision and its rationale>"
```

If the criterion genuinely fails for this story, record the explicit
zero (lets retros distinguish ran-and-found-none from skipped):

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-accept" \
  --content "story-NNN: no design decisions to record" \
  --working-on '[]'
```

The explicit-zero is not a shortcut — a story that rewrote non-trivial
logic almost always made at least one decision worth a slug + sentence.

### Step 2b.ii: Invoke /xp-story-close

/xp-story-close owns the per-story review + merge + JIT-create-next
pipeline:

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
the loop completes (single source of truth).

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
closed story when one existed.

## Step 5: Sprint Review

**If all stories are now done or deferred**, the sprint is complete. Run `/xp-sprint-review` immediately — do not wait for the stop gate.
