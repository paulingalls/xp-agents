---
name: xp-assign
description: >-
  Spawn ONE teammate per invocation — the lowest-id un-spawned story in the
  teammate batch, with the story's executor_model forwarded to spawn_teammate's
  --model flag. Runs once per story after that story's plan is reviewed, as
  part of the per-story plan→review→spawn loop. Parallel execution only —
  solo is /xp-schedule.
allowed-tools:
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(*/scripts/spawn_teammate.py *)
  - Bash(python3 */scripts/branching.py *)
  - Bash(python3 */smm/sprint_cli.py *)
  - Bash(git checkout *)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Work Assignment

> **Sequential discipline.** The harness batches independent tool calls in
> parallel; this skill is step-gated. Run Pre-flight → Branch → Prompt →
> Spawn → Post-spawn strictly, one step per turn — make the call, observe,
> then decide the next. Each /xp-assign invocation spawns exactly ONE
> teammate; the lead loops externally (plan → /xp-review-plan → /xp-assign,
> repeat per story). Never spawn the same subagent twice. Independent
> read-only calls may still batch.

Spawn one teammate per invocation as part of the **per-story
plan→review→spawn pipeline**. The decide-half (solo vs parallel, promotion,
solo branch) belongs to `/xp-schedule`: by the time xp-assign runs,
`/xp-schedule` has already promoted the batch to `in-progress` with
`execution_mode=teammate`, and the preload lists them as
`TEAMMATE_STORY_IDS`. The lead per-story plans→reviews→assigns one story
at a time; each /xp-assign run spawns the lowest-id un-spawned story in
the batch and exits.

**Parallelism shape:** earlier teammates run asynchronously while the
lead plans + spawns the next story (the Bash `run_in_background=true`).
As each teammate's task-notification fires, run `/xp-accept` on THAT
teammate before its sibling stories pile up unaccepted — accepts and
spawns interleave; they're not serialized.

## Pre-flight

1. If no `PLAN_FILE` — output "No plan file found. Enter plan mode for the next un-spawned story first." Stop.
2. Read the plan at `PLAN_FILE` — this is the most-recent per-story plan, written by `/xp-review-plan`.
3. If `SPRINT_FILE` provided, read it for story context (optional — status tracking only).
4. If `TEAMMATE_STORY_IDS` is empty — there is no teammate batch to assign. Stop. A solo frontier never reaches xp-assign; `/xp-schedule` branched it directly.
5. **Target lookup** — find the lowest-id story in `TEAMMATE_STORY_IDS` whose teammate worktree is NOT yet live:
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

## Step 1: Read the story's executor_model (optional)

```bash
STORY_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} get-story "$TARGET") \
  || { echo "get-story failed for $TARGET — fix sprint.json before spawning" >&2; exit 1; }
[ -n "$STORY_JSON" ] \
  || { echo "get-story returned empty for $TARGET — refusing to spawn" >&2; exit 1; }
EXECUTOR_MODEL=$(echo "$STORY_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('executor_model') or '')") \
  || { echo "executor_model parse failed for $TARGET — fix sprint.json before spawning" >&2; exit 1; }
```

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

If `$EXECUTOR_MODEL` is non-empty, append `--model "$EXECUTOR_MODEL"`.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py --name "worktree-$TARGET" \
  --smm-dir ${SMM_DIR} --prompt-file "/tmp/prompt-$TARGET.txt" \
  --story-id "$TARGET" --branch <story-branch> \
  --plugin-dir ${CLAUDE_PLUGIN_ROOT} \
  ${EXECUTOR_MODEL:+--model "$EXECUTOR_MODEL"} 2>&1 \
  | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_output_filter.py \
  --smm-dir ${SMM_DIR} --teammate-id "worktree-$TARGET"
```

Single Bash call with `run_in_background=true` — not a parallel batch. The teammate runs asynchronously; this skill returns immediately so the lead can continue with the next story.

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
