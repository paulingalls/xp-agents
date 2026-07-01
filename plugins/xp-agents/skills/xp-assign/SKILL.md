---
name: xp-assign
description: >-
  The universal per-story execution-shape decision. Reads the session default
  tier and the plan-reviewer's per-story recommendation, then applies a behavior
  table: it may exit in-agent (no spawn — continue in the existing checkout) or
  spawn exactly ONE teammate at the chosen tier (the story's executor_model
  forwarded to spawn_teammate's --model flag). Valid for solo and parallel
  frontiers alike. Runs once per story after that story's plan is reviewed.
allowed-tools:
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(*/scripts/spawn_teammate.py *)
  - Bash(python3 */scripts/branching.py *)
  - Bash(python3 */smm/sprint_cli.py *)
  - Bash(*/smm/append.sh *)
  - Bash(git checkout *)
  - AskUserQuestion
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Work Assignment

> **Sequential discipline.** The harness batches independent tool calls in
> parallel; this skill is step-gated. Run Pre-flight → Execution-shape
> decision → Branch → Prompt → Spawn → Post-spawn strictly, one step per
> turn — make the call, observe, then decide the next. Each /xp-assign
> invocation resolves ONE story: it either exits in-agent (no spawn) or
> spawns exactly ONE teammate — never more, never the same subagent twice.
> The lead loops externally (plan → /xp-review-plan → /xp-assign, repeat per
> story). Independent read-only calls may still batch.

/xp-assign is the **universal per-story execution-shape decision**: for one
story, it reads the session default tier and the plan-reviewer's
recommendation and decides whether to run the work in-agent (no spawn) or to
spawn a teammate, and at which tier. It is valid for both solo and parallel
frontiers — the decision is the same shape either way; only the spawn outcome
differs. The structural decide-half (solo vs parallel, promotion, solo branch)
still belongs to `/xp-schedule`: for parallel frontiers, by the time xp-assign
runs `/xp-schedule` has already promoted the batch to `in-progress` with
`execution_mode=teammate` and the preload lists them as `TEAMMATE_STORY_IDS`.
The lead per-story plans→reviews→assigns one story at a time; each /xp-assign
run resolves the lowest-id un-spawned story in the batch and exits.

**Parallelism shape:** earlier teammates run asynchronously while the
lead plans + spawns the next story (the Bash `run_in_background=true`).
As each teammate's task-notification fires, run `/xp-accept` on THAT
teammate before its sibling stories pile up unaccepted — accepts and
spawns interleave; they're not serialized.

## Pre-flight

1. If no `PLAN_FILE` — output "No plan file found. Enter plan mode for the next un-spawned story first." Stop.
2. Read the plan at `PLAN_FILE` — this is the most-recent per-story plan, written by `/xp-review-plan`.
3. If `SPRINT_FILE` provided, read it for story context (optional — status tracking only).
4. **Mode + target.** If `TEAMMATE_STORY_IDS` is non-empty → teammate batch (`MODE=teammate`); resolve `TARGET` via step 5. Else if `SOLO_TARGET` is non-empty → solo frontier (`MODE=solo`); set `TARGET=$SOLO_TARGET` and skip step 5 (no worktree to look up). Else nothing to assign — stop.
5. **Target lookup (teammate batch only).** When `MODE=teammate`, find the lowest-id story in `TEAMMATE_STORY_IDS` whose teammate worktree is NOT yet live:
   ```bash
   TARGET=""
   for sid in $TEAMMATE_STORY_IDS; do
     WT=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
       find-teammate-worktree --story-id "$sid" --cwd .)
     if [ -z "$WT" ]; then
       TARGET="$sid"
       break
     fi
   done
   ```
   If `TARGET` is empty — every teammate in the batch is already spawned. Output "All teammates spawned; /xp-accept each as it lands." Stop.

   The auto-detect assumes the lead plans stories in id order. If you need to spawn out-of-order, plan + /xp-review-plan + /xp-assign one story at a time — never plan multiple stories then call /xp-assign repeatedly, or the wrong plan will be paired with the wrong story.

   **Stale-spawn check.** `find-teammate-worktree` returns empty for THREE distinct cases: (a) story is genuinely un-spawned (correct target), (b) earlier spawn crashed before worktree-create (story still in-progress, no live teammate), (c) `/xp-story-close` cleaned the worktree after merge (story should be `done`, not still in-progress). For the chosen `TARGET`, check sprint.json: if the story is already in-progress AND no `session_init` event references it, the prior spawn likely crashed. **Ask the user**: re-spawn fresh, defer the story, or investigate first — don't silently re-target.

## Step 0: Execution-shape decision (the behavior table)

Before spawning, decide the execution shape for `TARGET` from two preload
inputs: `TEAMMATE_DEFAULT` (the session default tier — `off`/`haiku`/`sonnet`/
`opus`/`fable`/`inherit`) and `RECOMMENDED_TIER` (the plan-reviewer's per-story
pick — `in-agent`/`haiku`/`sonnet`/`opus`/`fable`/`none`, where `none` means it
was omitted or retracted as ambiguous). The preload computed `RECOMMENDED_TIER` for the SAME story this
skill spawns; `RECOMMENDED_TIER_STORY` echoes that target. **Verify
`RECOMMENDED_TIER_STORY` equals the `TARGET` you resolved in pre-flight before
applying `RECOMMENDED_TIER`.** If they differ, the un-spawned frontier shifted
between preload and now — treat `RECOMMENDED_TIER` as `none` (apply the default)
rather than misapply another story's recommendation to this `TARGET`.

Evaluate the branches **in this order** and act on the first that matches:

| # | Condition | Action |
|---|---|---|
| 1 | `TEAMMATE_DEFAULT` is `off` | **Exit, no spawn.** Output a one-line hint pointing at the kickoff teammate-support setting (re-run /xp-kickoff or flip the setting to enable teammates). |
| 2 | `--in-agent` flag passed | **Force in-agent. Exit, no spawn.** Output "this story is in-agent appropriate; continue in the existing checkout." Write a tier_override event UNLESS `RECOMMENDED_TIER` was also `in-agent` (then the pick matches — no override). |
| 3 | `RECOMMENDED_TIER` is `in-agent` | **Exit, no spawn.** Output "continue here — spawning a teammate is pure overhead for this story." No override event: the pick matches the recommendation. |
| 4 | `RECOMMENDED_TIER` matches `TEAMMATE_DEFAULT` (both a tier in `haiku`/`sonnet`/`opus`/`fable`) | **Silent spawn** at that tier: set the story's `executor_model` and forward `--model`. No question. |
| 5 | `RECOMMENDED_TIER` is a tier that **diverges** from `TEAMMATE_DEFAULT` | Ask EXACTLY ONE `AskUserQuestion`: apply the recommended tier `Y`, or keep the default `X`? Spawn at the chosen tier. If the customer keeps the default (rejects the recommendation), write a tier_override event. |
| 6 | `RECOMMENDED_TIER` is `none` | **Silent apply the default.** If `TEAMMATE_DEFAULT` is a tier, spawn at it; if it is `inherit`, spawn with NO `--model` flag (orchestrator tier). No override event. |

For the spawning branches (4–6), set the chosen tier on the story so Step 1
reads it back and Step 4 forwards it:

```bash
echo '{"executor_model":"<haiku|sonnet|opus|fable>"}' \
  | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} edit-story "$TARGET"
```

Leave `executor_model` unset for the `inherit` outcome (branch 6) — an absent
value is what makes Step 4 omit `--model` and inherit the orchestrator tier.

**Effort forward (per-story).** On a spawning branch, when `RECOMMENDED_EFFORT`
(the preload's per-story effort, from the same winning recommendation event) is
non-empty, also set the story's `executor_effort` so Step 4 forwards `--effort`:

```bash
echo '{"executor_effort":"<RECOMMENDED_EFFORT>"}' \
  | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} edit-story "$TARGET"
```

Leave it unset when `RECOMMENDED_EFFORT` is empty. No gating here: `spawn_teammate`
fail-safes — dropping `--effort` when the tier can't support the level — so it
degrades to the model default rather than erroring.

**In-agent invariant.** `in-agent` is a control-flow signal, not a tier — it is
**never** written to `executor_model`. It only ever drives the exit / no-spawn
branches (2 and 3). The spawning branches set `executor_model` ONLY to a valid
tier in `haiku`/`sonnet`/`opus`, or leave it null (the `inherit` outcome). A
spawn never carries `in-agent` as a model.

**Override audit event.** When the chosen tier differs from the recommendation
(branch 2's forced in-agent, or branch 5 when the customer keeps the default),
record it so the override-accuracy analysis can sample it:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir ${SMM_DIR} \
  --type "status" --agent "main" --working-on '[]' \
  --content "tier-override $TARGET: chose <picked> over recommended <reviewer>" \
  --metadata '{"action": "tier_override", "story_id": "'"$TARGET"'", "picked": "<tier>", "recommended": "<tier>"}'
```

`metadata.action` is `tier_override` — the contract the override-audit analysis
reads. The matching branches (1, 3, 4, 6) write no override event.

**Solo spawn = in-place.** A `MODE=teammate` spawn runs Steps 2–4 (worktree); a
`MODE=solo` spawn runs in the main checkout (Step 4 in-place variant),
`execution_mode` stays solo (solo accept/close path). Solo delegation pays only
at a CHEAPER tier — solo + `inherit` (same tier as the orchestrator) continues
in-agent, no spawn. In-agent outcomes never spawn.

## Step 1: Read the story's executor_model (optional)

```bash
STORY_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} get-story "$TARGET") \
  || { echo "get-story failed for $TARGET — fix sprint.json before spawning" >&2; exit 1; }
[ -n "$STORY_JSON" ] \
  || { echo "get-story returned empty for $TARGET — refusing to spawn" >&2; exit 1; }
EXECUTOR_MODEL=$(echo "$STORY_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('executor_model') or '')") \
  || { echo "executor_model parse failed for $TARGET — fix sprint.json before spawning" >&2; exit 1; }
EXECUTOR_EFFORT=$(echo "$STORY_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('executor_effort') or '')") \
  || { echo "executor_effort parse failed for $TARGET — fix sprint.json before spawning" >&2; exit 1; }
```

`executor_effort` (set on a spawning branch above) forwards to spawn_teammate's
`--effort` below when non-empty, guarded by that script's fail-safe; absent → no
`--effort`.

`executor_model` (story-002 schema slot) is optional. When set to `sonnet`/`opus`/`haiku`/`fable`, it is forwarded to spawn_teammate's `--model` flag below. When absent (null or missing field), no `--model` flag is passed (the spawned teammate inherits the orchestrator's model). The three-step shape (capture → non-empty check → parse-with-error-trap) surfaces every failure mode: non-zero exit (step 1), empty stdout on exit 0 (step 2), and malformed JSON / unexpected shape (step 3). A silent empty `$EXECUTOR_MODEL` would otherwise drift the spawn to the orchestrator's tier when the story actually specified one.

## Step 2: Create the story branch (Stage 1+)

`/xp-schedule` already promoted the story to `in-progress` with
`execution_mode=teammate`; xp-assign only creates the branch the teammate
worktree spawns into. If stage < 1, skip branch creation entirely.

```bash
BASE=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} get-base --cwd .)
git checkout "$BASE"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  create --cwd . --story "$TARGET" --slug <title-slug> --base "$BASE"
git checkout "$BASE"
```

## Step 3: Write the prompt file for THIS story

Write a self-contained prompt for `$TARGET` to `/tmp/prompt-$TARGET.txt`. The teammate has no prior context. Include:

- **Milestone Context** — design_details and constraints from execution_plan.json
- **Story Context** — what THIS story uniquely does (don't restate milestone rationale)
- **File Domain** — files this story exclusively owns
- **What to Change** — detailed changes from `PLAN_FILE`
- **Acceptance Criteria** — derived from the story record
- **Interface Contracts** — shared boundaries with other stories
- **Story Branch** — the branch name created in Step 2 (from sprint.json `branch_name`)
- **SMM Directory** — `SMM_DIR=<path>`
- TDD + review cycle instructions

## Step 4: Spawn ONE teammate async

Launch via Bash with `run_in_background`, passing `--story-id $TARGET`,
`--branch <story-branch>`, and `--plugin-dir ${CLAUDE_PLUGIN_ROOT}`. The
`--plugin-dir` is **required**: a headless `claude -p` worktree session
does not apply the project-scoped marketplace enablement, so without it
the teammate loads none of the xp-agents skills, agents, or hooks (no
TDD/review/commit gates, no SMM event recording). `${CLAUDE_PLUGIN_ROOT}`
resolves to the lead's live plugin dir, so the teammate runs the same
plugin version as the lead.

If `$EXECUTOR_MODEL` is non-empty, append `--model "$EXECUTOR_MODEL"`; if
`$EXECUTOR_EFFORT` is non-empty, append `--effort "$EXECUTOR_EFFORT"` (the
spawn fail-safes when the tier can't support the level).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py --name "worktree-$TARGET" \
  --smm-dir ${SMM_DIR} --prompt-file "/tmp/prompt-$TARGET.txt" \
  --story-id "$TARGET" --branch <story-branch> \
  --plugin-dir ${CLAUDE_PLUGIN_ROOT} \
  ${EXECUTOR_MODEL:+--model "$EXECUTOR_MODEL"} \
  ${EXECUTOR_EFFORT:+--effort "$EXECUTOR_EFFORT"} 2>&1 \
  | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_output_filter.py \
  --smm-dir ${SMM_DIR} --teammate-id "worktree-$TARGET"
```

Single Bash call with `run_in_background=true` — not a parallel batch. The teammate runs asynchronously; this skill returns immediately so the lead can continue with the next story.

**Solo in-place variant (`MODE=solo` spawn).** Skip Step 2 (the solo branch
exists). Spawn **in the main checkout**: add `--in-place`, drop
`--branch` (current branch), keep the `worktree-`-prefixed `--name` (detection
keys on it):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py --name "worktree-$TARGET" \
  --smm-dir ${SMM_DIR} --prompt-file "/tmp/prompt-$TARGET.txt" \
  --story-id "$TARGET" --in-place \
  --plugin-dir ${CLAUDE_PLUGIN_ROOT} \
  ${EXECUTOR_MODEL:+--model "$EXECUTOR_MODEL"} \
  ${EXECUTOR_EFFORT:+--effort "$EXECUTOR_EFFORT"} 2>&1 \
  | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_output_filter.py \
  --smm-dir ${SMM_DIR} --teammate-id "worktree-$TARGET"
```

`run_in_background=true`, then **wait**: end your turn and make NO edits in the
main checkout until the task-notification fires (it commits to the solo branch in
place). On it, run `/xp-accept` for `$TARGET` (still `in-progress`/solo → solo
path).

## Step 5: Post-spawn

The Bash above runs with `run_in_background=true`. You'll receive a `task-notification` when the teammate exits.

**Surface the teammate's exit to the user when the notification fires** — don't silently move on:
- **Read the teammate's stdout output file** named in the notification (the `teammate_output_filter.py` tee'd it). The last line is the token-cost summary; earlier lines name the story branch and the structured **report file path** the teammate wrote.
- **Then open the report file** for the structured what-shipped narrative — this is what /xp-accept and the eventual retro need; don't skip it.
- **If exit was non-zero** — the teammate crashed (worktree-create race, prompt-file missing, --plugin-dir resolution, agent error). Tell the user immediately; ask whether to re-spawn (delete the partial worktree first if any), defer the story, or investigate. The story is still `in-progress` with no live teammate.
- **If exit was 0** — run `/xp-accept` for `$TARGET` (verify + close) AS its notification fires; don't accumulate unaccepted teammates. Spawns and accepts interleave: while one teammate runs, the lead plans + spawns the next story; when a notification arrives, the lead pauses planning to accept the one that just finished. Letting many in-flight teammates pile up unaccepted drifts the sprint frontier.

The orchestrator does NOT merge teammate branches. Each story branch stays
alive on its teammate worktree until its `/xp-story-close` invocation
merges it (dispatched by `/xp-accept` per accepted story).
