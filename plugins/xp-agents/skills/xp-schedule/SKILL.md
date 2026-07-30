---
name: xp-schedule
description: >-
  Decide solo or parallel execution for the ready frontier, then promote the
  chosen stories and set each execution_mode. Runs before planning.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */smm/sprint_cli.py *)
  - Bash(python3 */scripts/branching.py *)
  - Bash(git checkout *)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Schedule the Next Frontier

> **Sequential discipline.** The harness batches independent tool calls in
> parallel; this skill is step-gated. Run Read-frontier → Mode → Promote → Next
> strictly, one step per turn — make the call, observe, then decide the next.
> Never put the mode `AskUserQuestion` and the promote/branch it gates in one
> block; never spawn the same subagent twice. Independent read-only calls may
> still batch.

Decide solo vs parallel for the **ready frontier** — the dep-satisfied
`scheduled` stories — then promote it. This precedes planning because the choice
sets the planning scope: solo plans one story; parallel locks per-story
file-domain disjointness up front, then the lead per-story plans→reviews→spawns
each teammate in turn. The preload computes the frontier; this skill consumes
it. `execution_mode` is a durable story field (`solo`/`teammate`) read later by
the plan-review gate (`subagent_stop`) and retro analysis.

## Step 1: Read the frontier

The preload emits `FRONTIER_IDS` (space-separated), `FRONTIER_COUNT`, and
`PARALLELIZABLE` (`true` only when the frontier has >=2 stories that form an
antichain — no story depends on another, directly or transitively — with
disjoint file domains). If `FRONTIER_COUNT` is `0`, there is nothing ready to
schedule (no dep-satisfied scheduled story) — report that and stop.
`OVERLAP_DETAIL`/`GLOB_FORCED` explain a false PARALLELIZABLE **when set**; a
false verdict with both empty means these stories cannot run concurrently for
a different reason — a dependency edge within the frontier.

## Step 2: Choose the mode (gate)

**Teammate support gate:** When `TEAMMATE_ENABLED == false` (teammates are
disabled for this session), auto-solo silently and skip the entire mode
decision tree below. Proceed directly to Step 3.

Otherwise, when teammate support is enabled:

- `FRONTIER_COUNT == 1` → **solo**, no question.
- `FRONTIER_COUNT >= 2` and `PARALLELIZABLE == false` (these stories cannot
  run concurrently) → **solo**, no question (teammates would collide or one
  would be branched without the other's commits) — but
  report why instead of downgrading silently: name `OVERLAP_DETAIL`'s
  colliding stories/path when set; if `GLOB_FORCED`, note a glob domain
  blocks proving disjointness; if neither is set, the frontier carries a
  dependency edge between two of its members.
- `FRONTIER_COUNT >= 2` and `PARALLELIZABLE == true` → ask via `AskUserQuestion`:
  *"Solo (sequential) or CLI teammates (parallel)?"* Present the rationale
  (the disjoint frontier ids). Do not bundle this question with the Step 3
  promotion it gates.

## Step 3: Promote + set mode (+ solo branch)

Read the story base branch. Solo cuts the branch FROM `$BASE`, so `--required`
refuses to degrade to the release branch. No `set -e` here: without the `||`
guard an empty `$BASE` reaches `create --base ""`.

```bash
BASE=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  get-base --cwd . --required) \
  || { echo "HALT: story base unresolved" >&2; exit 1; }
```

**On HALT, stop.** Do not promote and do not branch. Report the stderr reason:
re-cut the sprint branch (`branching.py create-sprint`) or fix `sprint.json`'s
`branch_name`.

**Solo** — promote the lowest-id frontier story, mark its mode, JIT its branch:
```bash
FIRST=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} next-scheduled)
echo '{"execution_mode":"solo"}' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
  --smm-dir ${SMM_DIR} edit-story "$FIRST"
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} \
  update-story "$FIRST" in-progress
git checkout "$BASE"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir ${SMM_DIR} \
  create --cwd . --story "$FIRST" --slug <title-slug> --base "$BASE"
```
The rest of the frontier stays `scheduled` — the next frontier is re-assessed at
the following `/xp-schedule` run.

**Parallel** — for each `FRONTIER_IDS` story, set `execution_mode=teammate` and
promote to `in-progress`. Do **not** create branches — `/xp-assign` creates each
teammate branch at spawn time, per story, after that story's plan is reviewed.
```bash
for sid in $FRONTIER_IDS; do
  echo '{"execution_mode":"teammate"}' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
    --smm-dir ${SMM_DIR} edit-story "$sid"
  python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir ${SMM_DIR} \
    update-story "$sid" in-progress
done
```

**Stage 0-1:** skip branch creation; promotion + `execution_mode` still apply.

**Per-story `executor_model` (optional).** Each story's `executor_model` schema slot (`sonnet`/`opus`/`haiku`/`fable`/null) drives `/xp-assign`'s `--model` flag. Default null = inherit orchestrator. Set per story before `/xp-assign` runs when tier matters (mechanical refactor = `haiku`, architecture-heavy = `opus`). Substitute the literal story id — the `$sid` from the promotion loop is bound to the LAST iteration's id by this point (bash has no block scope), which is rarely the story you want:
```bash
echo '{"executor_model":"haiku"}' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py \
  --smm-dir ${SMM_DIR} edit-story story-NNN
```

## Step 4: Record + emit next step

Record the decision:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir ${SMM_DIR} \
  --type "decision" --agent "xp-schedule" --topic "execution-mode" \
  --content "Frontier mode: <Solo|CLI teammates> — <rationale>"
```

Then emit the next step:
- **Solo** → "Proceeding solo on `$FIRST` — after /xp-review-plan, run /xp-assign
  to pick the execution shape: continue in-agent (default), or delegate the work
  to a cheaper in-place teammate (runs in the main checkout at a lower tier)."
- **Parallel** → "Frontier promoted as teammate batch —
  per-story plan→review→spawn. For each story: EnterPlanMode →
  /xp-review-plan → /xp-assign spawns that teammate async, then
  continue to the next story while it runs."
