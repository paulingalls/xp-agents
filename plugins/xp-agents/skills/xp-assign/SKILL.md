---
name: xp-assign
description: >-
  Per-story execution-shape decision: continue in-agent, or spawn one
  teammate at the chosen tier. Runs once per story after its plan is
  reviewed.
allowed-tools:
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(*/scripts/spawn_teammate.py *)
  - Bash(python3 */scripts/branching.py *)
  - Bash(python3 */smm/sprint_cli.py *)
  - Bash(*/smm/append.sh *)
  - Bash(git checkout *)
  - Bash(git branch --merged *)
  - AskUserQuestion
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh --consume-gate`

# Work Assignment

> **Sequential discipline.** Run Pre-flight → Execution-shape decision →
> Branch → Prompt → Spawn → Post-spawn one step per turn — make the call,
> observe, then decide the next. Each invocation resolves ONE story: exit
> in-agent, or spawn exactly ONE teammate, never more.

/xp-assign makes the **per-story execution-shape decision** — in-agent (no
spawn) or one teammate spawn, and at which tier — identically on solo and
parallel frontiers; only the outcome differs. `/xp-schedule` owns the structural
half (solo vs parallel, promotion, solo branch): by the time xp-assign runs it
has promoted the batch to `in-progress` with `execution_mode=teammate`, which
the preload lists as `TEAMMATE_STORY_IDS`.

**Parallelism shape:** earlier teammates run asynchronously while the lead plans
the next story (Bash `run_in_background=true`). Precedence is **plan → SPAWN →
accept**: spawning never waits on an accept, or the background sits empty for a
whole close cycle.

## Pre-flight

1. If no `PLAN_FILE` — output "No plan file found. Enter plan mode for the next un-spawned story first." Stop.
2. Read the plan at `PLAN_FILE` — this is the most-recent per-story plan, written by `/xp-review-plan`.
3. If `SPRINT_FILE` provided, read it for story context (optional — status tracking only).
4. **Mode + target — solo-first.** If `SOLO_TARGET` is non-empty → solo frontier (`MODE=solo`); set `TARGET=$SOLO_TARGET` and skip step 5 (no worktree to look up). Else if `TEAMMATE_STORY_IDS` is non-empty → teammate batch (`MODE=teammate`); resolve `TARGET` via step 5. Else nothing to assign — stop.

   **A live solo story drains: while `SOLO_TARGET` names one there is no fall-through to the batch**, until it is accepted — a teammate spawn checks out the base branch (step 2) in the main checkout an in-place solo teammate is concurrently committing in. It is the one place the **plan → SPAWN → accept** precedence yields: re-invoking during that spawn earns only its refusal, and re-invoking after it exits re-runs the finished story (the exclusive claim is released at exit) — so its accept comes first.

   **The hole: >1 in-progress solo story.** The preload cannot pick one, so `SOLO_TARGET` arrives empty — indistinguishable from "no solo story", and empty is NOT proof the drain is over. Before selecting the batch, confirm `SPRINT_FILE` shows no `in-progress` + `execution_mode=solo` story; reconcile one that is (accept or defer) rather than spawn into its checkout.
5. **Target lookup (teammate batch only).** When `MODE=teammate`, resolve the lowest-id un-spawned story in `TEAMMATE_STORY_IDS` — the first whose teammate worktree is not yet live:
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

   The auto-detect assumes the lead plans stories in id order. To spawn out-of-order, plan + review + assign one story at a time — planning several, then calling /xp-assign repeatedly, pairs the wrong plan with the wrong story.

   **Stale-spawn check.** `find-teammate-worktree` returns empty for THREE cases: (a) genuinely un-spawned (correct target), (b) an earlier spawn crashed before worktree-create (still in-progress, no live teammate), (c) `/xp-story-close` cleaned the worktree after merge (story should be `done`). Only (a) is "spawn it", and sprint.json's `branch_name` discriminates: null → no branch was ever cut → (a); non-null → Step 2 already ran, so (b) or (c) — **ask the user** (re-spawn, close it, or investigate); don't silently re-target. `git branch --merged "$BASE"` (`$BASE` via Step 2's `get-base`; unset in pre-flight) separates those two: it lists the branch when the merge landed but the close stopped before deleting it. A completed close DELETES the branch, so absence is the ordinary shape of (c), never evidence of (a). A live duplicate cannot hide here: a worktree teammate has a worktree, so this lookup finds it; an in-place teammate is refused by the spawn's exclusive per-name claim.

## Step 0: Execution-shape decision (the behavior table)

Decide the execution shape for `TARGET` from two preload inputs:
`TEAMMATE_DEFAULT` (the session default tier — `off`/`haiku`/`sonnet`/`opus`/
`fable`/`inherit`) and `RECOMMENDED_TIER` (the plan-reviewer's per-story pick —
`in-agent`/`haiku`/`sonnet`/`opus`/`fable`/`none`, where `none` means it was
omitted or retracted as ambiguous). **Verify `RECOMMENDED_TIER_STORY` equals the
`TARGET` you resolved in pre-flight before applying `RECOMMENDED_TIER`.** If they
differ, the un-spawned frontier shifted between preload and now — treat
`RECOMMENDED_TIER` as `none` rather than misapply another story's recommendation.

Evaluate the branches **in this order** and act on the first that matches:

| # | Condition | Action |
|---|---|---|
| 1 | `TEAMMATE_DEFAULT` is `off` | **Exit, no spawn.** Output a one-line hint at the kickoff teammate-support setting (re-run /xp-kickoff to enable teammates). |
| 2 | `--in-agent` flag passed | **Force in-agent. Exit, no spawn.** Output "this story is in-agent appropriate; continue in the existing checkout." Write a tier_override event UNLESS `RECOMMENDED_TIER` was also `in-agent` (the pick matches). |
| 3 | `RECOMMENDED_TIER` is `in-agent` | **Exit, no spawn.** Output "continue here — spawning a teammate is pure overhead for this story." No override event: the pick matches the recommendation. |
| 4 | `RECOMMENDED_TIER` matches `TEAMMATE_DEFAULT` (both a tier in `haiku`/`sonnet`/`opus`/`fable`) | **Silent spawn** at that tier: set the story's `executor_model` and forward `--model`. No question. |
| 5 | `RECOMMENDED_TIER` is a tier that **diverges** from `TEAMMATE_DEFAULT` | Ask EXACTLY ONE `AskUserQuestion`: apply the recommended tier `Y`, or keep the default `X`? Spawn at the chosen tier. If the customer keeps the default (rejects the recommendation), write a tier_override event. |
| 6 | `RECOMMENDED_TIER` is `none` | **Silent apply the default.** If `TEAMMATE_DEFAULT` is a tier, spawn at it; if it is `inherit`, spawn with NO `--model` flag (orchestrator tier). No override event. |

For the spawning branches (4–6), persist the decision with `set-executor`, which
writes a field only when its flag is passed (provided-empty → `null`; omitted →
untouched):

- **`executor_model`** is also settable by a `/xp-schedule` per-story pre-seed, so
  pass `--model "<tier>"` only when the outcome is a concrete tier, and **omit
  `--model` on any `inherit` outcome** so the pre-seed is preserved, not clobbered.
- **`executor_effort`** (sole writer: this decision) is passed on **every**
  spawning branch, value-or-null — `${RECOMMENDED_EFFORT}` at the recommended
  tier, else `--effort ""` — which clears any latched `executor_effort`.

```bash
# Concrete tier (branch 4/5, or branch 6 tier default):
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} \
  set-executor "$TARGET" --model "<chosen-tier>" --effort "<RECOMMENDED_EFFORT-or-empty>"
# Inherit outcome — clear effort, omit --model to preserve any pre-seed:
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} \
  set-executor "$TARGET" --effort ""
```

`spawn_teammate` fail-safes on effort (drops `--effort` when the tier can't
support it), degrading to the model default rather than erroring.

**In-agent invariant.** `in-agent` is a control-flow signal, not a tier — it is
**never** written to `executor_model`. It only ever drives the exit / no-spawn
branches (2 and 3). The spawning branches set `executor_model` ONLY to a valid
tier in `haiku`/`sonnet`/`opus`, or leave it untouched on the `inherit` outcome.

**Override audit event.** When the chosen tier differs from the recommendation
(branch 2's forced in-agent, or branch 5 when the customer keeps the default),
record it so the override-accuracy analysis can sample it:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir ${SMM_DIR} \
  --type "status" --agent "main" --working-on '[]' \
  --content "tier-override $TARGET: chose <picked> over recommended <reviewer>" \
  --metadata '{"action": "tier_override", "story_id": "'"$TARGET"'", "picked": "<tier>", "recommended": "<tier>"}'
```

The matching branches (1, 3, 4, 6) write no override event.

**Solo spawn = in-place.** A `MODE=teammate` spawn runs Steps 2–4 (worktree); a
`MODE=solo` spawn runs in the main checkout (Step 4 in-place variant),
`execution_mode` stays solo (solo accept/close path). Solo delegation pays only
at a CHEAPER tier — solo + `inherit` (same tier as the orchestrator) continues
in-agent, no spawn.

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

Both fields are optional, and Step 4 forwards each when non-empty. Each command
above traps its own failure mode because a silently empty `$EXECUTOR_MODEL`
would drift the spawn to the orchestrator's tier when the story specified one.

## Step 2: Create the story branch (Stage 1+)

xp-assign only creates the branch the teammate worktree spawns into. If
stage < 1, skip branch creation entirely.

The branch is cut FROM `$BASE`, so `--required` refuses to degrade to the
release branch. There is no `set -e` here: without the `||` guard an empty
`$BASE` falls through to `create --base ""`.

```bash
BASE=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  get-base --cwd . --required) \
  || { echo "HALT: story base unresolved" >&2; exit 1; }
git checkout "$BASE"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  create --cwd . --story "$TARGET" --slug <title-slug> --base "$BASE"
git checkout "$BASE"
```

**On HALT, stop the assign.** Do not spawn the teammate and do not pick a base
by hand. Report the stderr reason: re-cut the sprint branch
(`branching.py create-sprint`) or fix `sprint.json`'s `branch_name`.

## Step 3: Write the prompt file for THIS story

First resolve the per-project prompt path — a flat `/tmp/prompt-$TARGET.txt`
collides across concurrent sessions in different projects (story ids repeat),
so query the collision-safe path from the spawn script (it creates the parent
dir, and fails loud if it can't):

```bash
PROMPT_FILE=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py \
  --print-prompt-path --name "worktree-$TARGET" --smm-dir ${SMM_DIR})
```

Write a self-contained prompt for `$TARGET` to `$PROMPT_FILE` in THIS same Bash
call's turn (with the Write tool, using the printed path). The spawn in Step 4
re-derives this exact path from `--name` + `--smm-dir`, so you do NOT thread
`$PROMPT_FILE` into the spawn command — a shell variable would be empty in the
separate Bash call anyway. The teammate has no prior context. Include:

- **Milestone Context** — design_details and constraints from execution_plan.json
- **Story Context** — what THIS story uniquely does (don't restate milestone rationale)
- **File Domain** — files this story exclusively owns
- **What to Change** — detailed changes from `PLAN_FILE`
- **Acceptance Criteria** — derived from the story record
- **Interface Contracts** — shared boundaries with other stories
- **Story Branch** — the story branch created in Step 2, **verbatim**: the same
  string you pass to `--branch` in Step 4 (the story's own `branch_name`, NOT
  the sprint-level one). Do not shorten it to the story id, re-slug it, or
  prettify it.
- **SMM Directory** — `SMM_DIR=<path>`
- TDD instructions. **Do not state the review cadence** — the teammate's own
  session start renders it from live state, and its commit gate reports the one
  in force. A copy written here is a channel that can only go stale.

**The branch is a hard gate, not a nicety.** The spawn refuses any prompt that
does not contain the `--branch` string, and exits non-zero without spawning.
Story ids repeat every sprint and nothing invalidates a prompt file, so a prompt
naming only `story-003` is indistinguishable from a stale one written for LAST
sprint's story-003 — the branch (id + slug) is the only thing that tells them
apart, so a paraphrased branch fails the spawn exactly as a stale prompt does.

The solo `--in-place` variant below passes no `--branch`, so the spawn can only
fall back to checking the story id there — a weaker check, since both sprints'
prompts carry the same id. Write the branch verbatim anyway.

## Step 4: Spawn ONE teammate async

Launch via a single Bash call with `run_in_background=true` — not a parallel
batch — passing `--story-id $TARGET`, `--branch <story-branch>`, and
`--plugin-dir ${CLAUDE_PLUGIN_ROOT}`. The `--plugin-dir` is **required**: a
headless `claude -p` worktree session does not apply the project-scoped
marketplace enablement, so without it the teammate loads none of the xp-agents
skills, agents, or hooks. `${CLAUDE_PLUGIN_ROOT}` resolves to the lead's live
plugin dir, so the teammate runs the same plugin version as the lead.

If `$EXECUTOR_MODEL` is non-empty, append `--model "$EXECUTOR_MODEL"` to the
command below; if `$EXECUTOR_EFFORT` is non-empty, append
`--effort "$EXECUTOR_EFFORT"`. Append them as literal words — a
conditional-expansion one-liner is bash-only and mis-parses under zsh.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py --name "worktree-$TARGET" \
  --smm-dir ${SMM_DIR} \
  --story-id "$TARGET" --branch <story-branch> \
  --plugin-dir ${CLAUDE_PLUGIN_ROOT} 2>&1 \
  | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_output_filter.py \
  --smm-dir ${SMM_DIR} --teammate-id "worktree-$TARGET"
```

**Solo in-place variant (`MODE=solo` spawn).** Skip Step 2 (the solo branch
exists). Spawn **in the main checkout**: add `--in-place`, drop
`--branch` (current branch), keep the `worktree-`-prefixed `--name` (detection
keys on it):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py --name "worktree-$TARGET" \
  --smm-dir ${SMM_DIR} \
  --story-id "$TARGET" --in-place \
  --plugin-dir ${CLAUDE_PLUGIN_ROOT} 2>&1 \
  | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_output_filter.py \
  --smm-dir ${SMM_DIR} --teammate-id "worktree-$TARGET"
```

`run_in_background=true`, then **wait**: end your turn and make NO edits in the
main checkout until the task-notification fires (it commits to the solo branch in
place). On it, run `/xp-accept` for `$TARGET` (still `in-progress`/solo → solo
path).

**Surface the live forensic log (both variants).** Right after launching, tell
the lead where to watch mid-flight. The `.log` is line-flushed live
(`run_with_tee`), so `tail -F` shows progress and diagnoses a stall in real time
— unlike the task output, which stays ~empty until exit. Use `-F`, not `-f`: the
log only appears a few seconds in, and `-F` waits for it instead of erroring on
a not-yet-created path. Query the exact path and surface it:

```bash
LOG_PATH=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/spawn_teammate.py \
  --print-log-path --name "worktree-$TARGET" --smm-dir ${SMM_DIR})
echo "Teammate running in background. Watch it live / diagnose a stall: tail -F $LOG_PATH"
```

## Step 5: Post-spawn

You'll receive a `task-notification` when the background teammate exits.

**Surface the teammate's exit to the user when the notification fires** — don't silently move on:
- **Read the task output file** named in the notification. `teammate_output_filter.py` does NOT tee its stdin, so this file stays ~empty during the run, then holds one of two shapes: **on success**, one summary line naming the **report file path** (`Report: <path> | Branch: <branch> | Cost: $<n>`); **on a no-result failure**, several diagnostic lines plus a saved-artifact path — open that artifact for the full capture. Mid-flight, tail `$LOG_PATH` from Step 4 instead.
- **Then open the report file** for the structured what-shipped narrative — this is what /xp-accept and the eventual retro need; don't skip it.
- **If exit was non-zero** — the teammate crashed (worktree-create race, prompt-file missing, --plugin-dir resolution, agent error). Tell the user immediately; ask whether to re-spawn (delete the partial worktree first if any), defer the story, or investigate. The story is still `in-progress` with no live teammate.
- **If exit was 0** — apply the pipeline's precedence rule before touching `/xp-accept`: if any story is planned, reviewed and un-spawned, spawn it FIRST, then accept `$TARGET`. If there is nothing left to spawn, accept `$TARGET` immediately — an exhausted spawn frontier must never stall acceptance. Either way `$TARGET` gets its `/xp-accept` (verify + close) on this notification, before sibling stories pile up unaccepted.

The orchestrator does NOT merge teammate branches. Each story branch stays
alive on its teammate worktree until its `/xp-story-close` invocation
merges it (dispatched by `/xp-accept` per accepted story).
