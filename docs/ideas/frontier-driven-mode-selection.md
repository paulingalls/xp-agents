# Frontier-Driven Mode Selection (`/xp-schedule`)

**Status:** design — not yet implemented
**Date:** 2026-06-08

## Problem

When a story is JIT-promoted after the previous one closes, agents skip
`/xp-assign` — they reason that branch creation and mode selection already
happened, so it's redundant. Their instinct is *partly correct*: re-running
the full xp-assign for an in-progress JIT story would over-promote the **next**
scheduled story (e.g. promote story-003 while story-002 is still in flight).
But skipping it leaves the `.assign-pending` write gate set by
`/xp-review-plan`, which then blocks the agent's first TDD write with a
confusing "run /xp-assign."

Root cause: **the mode decision and the plan-split/spawn are bundled into one
skill that runs once per sprint, but the system actually needs the mode
decision at every *frontier-open* point** — sprint start *and* each
story-close. xp-assign was built for the initial fully-parallel batch and is
not safe to re-run mid-sprint.

A second, related gap surfaced while tracing this: the design cannot express a
**sequential foundation → parallel fan-out** within one sprint (story-1 solo,
then stories 2–5 parallel once 1 lands). xp-assign decides mode *once* over the
whole scheduled set; the moment to parallelize 2–5 is *after* story-1 closes,
which is exactly the mid-sprint re-assess the current design forbids.

## Audit: what xp-assign does, and who depends on it

Confirmed there is **no hard downstream dependency** on a per-story assign:

| Side effect | Consumer |
|---|---|
| `rm .assign-pending` (preload) | the write gate — only matters because review-plan set it |
| `update-story … in-progress` | already done by story-close Step 8 for stories 2..N |
| `branching.py create` | already done by story-close Step 8 |
| `decision` event topic `execution-mode` | only `concerns.py` — a *defensive* supersession **exemption**; nothing requires the event |
| `assumption` "Domain boundary" (teammate only) | **zero consumers** |
| `STATUS_ACTION_ASSIGN_COMPLETE` | **zero consumers**; not a commit-gate flag |

Clinching evidence: stories 2..N **already ship today without a per-story
assign** (story-close JIT-promotes them; assign never runs), and story-close
emits neither `execution-mode` nor `assign_complete`. So those events are
already absent for every story after the first, across every shipped sprint.

## The model: mode follows the ready frontier

Mode is decided per **ready frontier** (dep-satisfied scheduled stories),
re-assessed at sprint start **and** at each story-close — not once globally.

- frontier `== 1` → solo: promote + branch, **no gate**, agent codes after review
- frontier `>= 2` disjoint domains → ask solo/parallel
  - solo → promote + branch the lowest-id ready story; the rest wait for the
    next frontier-open
  - parallel → record mode + batch; plan the batch; review; xp-assign splits +
    spawns off the post-foundation tip
- frontier `>= 2` overlapping → solo (parallel isn't safe)

The solo/parallel decision **must precede planning**, because it sets the
planning *scope*: plan one story (solo) vs. plan the whole batch so xp-assign
can split it per teammate. xp-assign stays **after** review — the teammate path
consumes the reviewed plan, and that must not be skipped.

## Ownership (status lifecycle unchanged)

`ready` → `scheduled` → `in-progress` → `closing` → `done`/`deferred`

| Transition | Owner | Notes |
|---|---|---|
| create → `ready` | sprint-start | unchanged |
| `ready` → `scheduled` | **work-selection** | customer subsetting + ad-hoc capture — unchanged |
| `scheduled` → `in-progress` + mode | **`/xp-schedule`** (new) | compute frontier, ask solo/parallel, promote; solo also creates+checks out the branch |
| split reviewed plan → spawn | **xp-assign** (narrowed) | parallel-only; solo never touches it |

## `/xp-schedule` (new skill)

The interactive **"decide" half** of today's xp-assign, split out so the
question lands before planning. A skill (not a script) because its core is an
`AskUserQuestion` + judgment; deterministic parts (frontier math, overlap
check, promote, solo-branch) live in a backing script.

Runs at two entry points, both as their final step:

```
kickoff:          … housekeeping → render → /xp-schedule → (plan mode | solo-branched)
accept post-loop: … per-story close loop done → /xp-schedule → (plan mode | solo-branched | sprint-review)
```

Responsibilities:
1. Compute the ready frontier over `scheduled` stories (dep-gated) — from the
   preload's `ready-frontier` vars.
2. If frontier `>= 2` disjoint → ask solo/parallel (apply the plan-driven
   heuristic; present rationale). Else auto-solo.
3. Promote the chosen frontier `scheduled → in-progress`.
4. Solo → create + checkout the branch (agent plans/codes on it).
   Parallel → record mode + batch (branches created later by xp-assign at spawn).
5. Set each promoted story's `execution_mode` field (`solo`/`teammate`) so the
   plan-review gate can read it.
6. Emit next step: enter plan mode, scoped to 1 or N stories.

## Touch points

1. **New `/xp-schedule` skill** + frontier script.
2. **work-selection** — unchanged (keeps `ready → scheduled`).
3. **xp-assign** — remove `scheduled→in-progress` promotion, the mode question,
   and solo branch creation; keep plan-split + teammate-branch + spawn. Becomes
   parallel-only; narrow its description accordingly.
4. **plan-reviewer gate** (`subagent_stop.py:_handle_plan_review_done`) — set
   `.assign-pending` only when the planned story's `execution_mode` is
   `teammate`.
5. **kickoff tail** — call `/xp-schedule` before plan mode.
6. **`/xp-accept` post-loop** — call `/xp-schedule` for the next frontier once
   the per-story close loop completes (single ask per accept run); falls
   through to sprint-review when no stories remain.
7. **story-close Step 8** — remove the JIT-next promote/branch dispatch;
   promotion now lives in `/xp-schedule`. story-close just merges + cleans up.
8. **schedule write gate** (`pre_tool_write.py`) — block non-plan/non-SMM
   writes in the trigger state (scheduled exist, none in-progress).
9. **schedule plan-mode gate** (`PreToolUse` on `EnterPlanMode`) — block plan
   entry in the same state, protecting plan scope.

## Enforcement

Prose can't guarantee `/xp-schedule` runs — agents reason their way out of
steps (the whole reason this thread exists), and a solo frontier of one story
is *more* tempting to skip ("just promote-and-branch inline"). Two deterministic
gates make skipping structurally impossible. Both are **state-derived, not
marker-based** — there is no file to `rm` past (a real bypass observed before
with `.assign-pending`); the only authentic signal is sprint state.

**Trigger condition (shared):** a sprint is active, `scheduled` stories exist,
and **zero** stories are `in-progress`. That is exactly the "work-selection
scheduled work but no frontier promoted yet" window, and `/xp-schedule` is the
sole owner of `scheduled → in-progress`, so it is the only legitimate exit.

1. **Write gate** (`pre_tool_write.py`) — in the trigger state, block non-plan,
   non-SMM writes: *"Run /xp-schedule to promote the next frontier and pick
   solo/teammate."* Self-clears the instant a frontier is promoted.
2. **Plan-mode gate** (`PreToolUse` on `EnterPlanMode`) — same condition.
   `/xp-schedule` must precede planning because it sets the planning *scope*
   (solo plans one story; teammate plans the batch so xp-assign can split it).
   Without this, the agent can plan the wrong unit before deciding.

These sit next to the narrowed `.assign-pending` gate — two gates, two steps:

| Gate | Fires when | Forces | Clears when |
|---|---|---|---|
| **schedule gate** (new, state-derived) | scheduled stories exist, none in-progress | `/xp-schedule` (before planning) | a frontier is promoted |
| **assign gate** (`.assign-pending`, narrowed) | plan reviewed AND planned story's `execution_mode == teammate` | `/xp-assign` (after review) | xp-assign spawns |

- Solo path: schedule gate → `/xp-schedule` → plan → review → *no* assign gate → code.
- Teammate path: schedule gate → `/xp-schedule` (sets `execution_mode=teammate`)
  → plan batch → review → assign gate → `/xp-assign` spawns.

Free mode / no sprint → no scheduled stories → neither gate fires. A fully
promoted sprint → no scheduled, none-blocked → no fire. The gate fires only in
the precise pre-promotion window.

## Decided

- **`/xp-schedule` runs in `/xp-accept`'s post-loop**, not story-close's tail —
  so the frontier is settled and it asks at most once per accept run. story-close
  drops its JIT-next dispatch entirely.
- Keep per-iteration subsetting in **work-selection** (`ready → scheduled`);
  `/xp-schedule` only does `scheduled → in-progress`. No `scheduled`-status
  collapse — status model stays intact.
- Name: **`/xp-schedule`** (it schedules the next planning unit).
- xp-assign keeps its name and its post-review plan-split/spawn role; it just
  loses promotion + the mode question.
- **Mode is a story field, not a status or a marker.** Add
  `execution_mode: "solo" | "teammate"` to the story. `/xp-schedule` sets it;
  `subagent_stop` reads it to gate. Keeps the status enum + its derived sets
  (`IN_MOTION`, `UNDER_ACCEPTANCE`, `TERMINAL`) untouched, and the value is
  durable (retro can analyze solo-vs-teammate later) rather than evaporating at
  `in-progress`.
- **Enforced by two state-derived gates**, not prose or markers — a write gate
  and an `EnterPlanMode` gate, both firing on "scheduled exist, none
  in-progress." See Enforcement. Skipping `/xp-schedule` becomes structurally
  impossible.
- **Frontier comes from the preload, computed in Python.** Add a
  `ready-frontier` entry point (scheduled stories whose deps are *all already*
  done + their mutual file-domain overlap). The `/xp-schedule` preload calls it
  and emits the set + parallelizable verdict as preload vars, so the skill just
  consumes them — no mid-flow CLI call, no dependency math in bash. (Existing
  `next-scheduled` returns one story; iterating it with `--treat-as-done`
  yields a *sequence*, not the simultaneous frontier; `scheduled-overlap`
  spans all scheduled, not just the frontier.)
