---
name: xp-kickoff
description: >-
  Session start orchestrator. Sequences retrospective, sprint setup,
  work selection, and housekeeping. Use at the start of every session.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */smm/retro_cli.py *)
  - Bash(python3 */smm/smm_cli.py *)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh`

# Session Kickoff

The session status above was preloaded automatically.

**You MUST complete ALL steps below in order. Do NOT stop after any single step. Do NOT start working on the user's goal until ALL steps are done. Housekeeping (step 6) MUST always run — it is not optional. Only after housekeeping completes should you begin working on the session goals.**

## Step 1: Retrospective (if RETRO_NEEDED)

If the preload shows **RETRO_NEEDED**, invoke the `xp-retrospective` agent directly via the Agent tool (`subagent_type=xp-agents:xp-retrospective`). The SubagentStart hook injects `SMM_DIR` and `RETRO_INPUT` into the agent's context; the agent reads `${SMM_DIR}/.retro-input.json`, analyzes it, and writes a timestamped file under `${SMM_DIR}/retrospectives/`. The session retro handles both regular sessions and sprint completions — when a sprint just ended, the retro input includes sprint sizing metrics automatically.

After the agent completes, render the latest retrospective:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/retro_cli.py --smm-dir <SMM_DIR> render
```

Output the render CLI's stdout to the user before continuing.

## Step 2: Session mode (ALWAYS)

Ask the user via AskUserQuestion: **"Free session or Sprint session?"**

- **Free session** — for brainstorming, Q&A, bug fixes, or any work that doesn't need sprint scaffolding.
- **Sprint session** — for planned work with product spec, sprint stories, and acceptance criteria.

After the user answers, record the session mode as a goal event so it flows into the Intent pillar:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "goal" --agent "xp-kickoff" \
  --content "Free session" # or "Sprint session: <sprint-id>"
```

If the user chooses **free session**: skip steps 3 and 4, jump directly to step 5 (Work Selection). In step 5, work selection should collect freeform session goals only — do NOT show sprint stories or prompt for story selection, even if a sprint exists.

If the user chooses **sprint session**: proceed to step 3.

## Step 2.4: Stage 2 floor migration prompt (ALWAYS, every kickoff)

This step runs at every kickoff regardless of the session mode chosen in Step 2 — the Stage 2 floor matters for both free and sprint sessions.

Read the branching stage:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage
```

If the stage is `>= 2`, **skip this step** — the project is already at the v3.1 plugin floor (Stage 2). Stage 1 auto-promotes to 2 inside `branching.py stage`, so only an explicit Stage 0 declaration reaches the gate below.

Otherwise (stage `< 2`), check whether the user has previously dismissed the prompt for this project — sticky dismissal so a deliberate Stage 0 declaration doesn't re-prompt every kickoff:
```bash
DISMISSED_AT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> \
  get-branching-field stage_prompt_dismissed_at)
```

If `DISMISSED_AT` is non-empty, **skip the prompt** — log a brief note to the user that includes the timestamp AND the re-opt-in command, so they can undo without grep'ing the SKILL: *"Stage 2 migration prompt was dismissed at {DISMISSED_AT}. To re-enable, run `printf null | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> edit-branching-field stage_prompt_dismissed_at`"*. The prompt re-fires only after the user clears the field or the stage declaration changes.

Otherwise prompt the user via `AskUserQuestion`, substituting the actual stage value into the prose: **"This project is on branching Stage <N>. Stage 2 is the v3.1 plugin floor (sprint branches required for production-grade discipline). Migrate now via /xp-sprint-start, or continue at Stage <N> for this session?"**

If the user picks **migrate**, invoke `/xp-sprint-start` immediately and let it walk through the upgrade. Do NOT record a dismissal — the migration path is the non-dismissed branch. After it completes, proceed to Step 2.5 (which re-reads stage fresh).

If the user picks **continue**, record the dismissal so the prompt sticks until the user opts back in:
```bash
TS=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())")
printf '%s' "\"$TS\"" | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> \
  edit-branching-field stage_prompt_dismissed_at
```

Then proceed to Step 2.5.

## Step 2.5: Auto-create free branch on protected (free sessions only)

If the user chose **free session** AND the branching stage is `>= 1` AND the current branch is a protected branch (`main` or `master`), create and check out a fresh free branch so the session never commits directly to a protected branch.

Read the stage:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage
```

If the stage is `0`, **skip this step** — Stage 0 has no branch discipline and free sessions are allowed on the protected branch. If the current branch is already a non-protected branch (e.g., the user is resuming a free branch), **skip this step** — do not nest branches.

Otherwise, create the free branch with a slug derived from the user's session goal (first 3-4 words, slugified):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  create-free --cwd . --slug "<session-goal-slug>"
```

`branching.py create-free` returns `<user>/free-YYYY-MM-DD-<slug>` and checks it out. Tell the user which branch was created so they can connect later commits to the free session.

## Step 2.6: Orphan free-branch triage (ALWAYS, every kickoff)

If the preload shows **ORPHAN_FREE_BRANCHES**, the user has unfinished free branches from prior sessions. For each branch listed, ask via `AskUserQuestion`: **merge / keep / delete?**

- **merge** — invoke `/xp-free-close` against that branch (check it out first if needed). The skill will run the close-reviewer, ask for merge confirmation, and merge into primary.
- **keep** — leave the branch alone; it will reappear at the next kickoff.
- **delete** — drop the branch unconditionally. Use `branching.py delete --branch <name>` only when the user explicitly confirms; do not auto-delete branches with commits ahead of primary.

This step runs at every kickoff regardless of the session mode chosen in Step 2 — orphan detection is a safety net for free sessions ended without `/xp-free-close`.

## Step 2.7: Orphan story-branch triage (ALWAYS, every kickoff)

If the preload shows **ORPHAN_STORY_BRANCHES**, the user has story branches not backed by any active (ready/in-progress/reviewing) sprint story. For each branch listed, ask via `AskUserQuestion`: **merge / keep / delete?**

- **merge** — merge the branch into the sprint base via `branching.py merge-branch --cwd . --branch <name>`, then delete it via `branching.py delete --cwd . --branch <name>`.
- **keep** — leave the branch alone; it will reappear at the next kickoff.
- **delete** — drop the branch via `branching.py delete --cwd . --branch <name>` only when the user explicitly confirms; do not auto-delete branches with commits ahead of the base.

This step runs at every kickoff regardless of session mode — orphan story branches accumulate when `/xp-accept` defers stories or sprints close without merging all branches.

## Step 3: System Context and Execution Plan (if NEEDS_SYSTEM_CONTEXT or NEEDS_EXECUTION_PLAN)

If the preload shows "NEEDS_SYSTEM_CONTEXT" and this is a sprint session, invoke `/xp-system-context`. Wait for it to complete before proceeding.

If the preload shows "NEEDS_EXECUTION_PLAN", first `Read` the SMM file at `<SMM_DIR>/shared_mental_model.json` for context (constraints, wisdom, and risks guide planning). Then invoke `/xp-plan`. Wait for it to complete before proceeding.

If neither is shown, skip to step 4.

## Step 4: Sprint Start (if NEEDS_SPRINT)

If the preload shows "NEEDS_SPRINT" and you haven't already read the SMM in step 3, `Read` the SMM file at `<SMM_DIR>/shared_mental_model.json` first. Then invoke `/xp-sprint-start`. Wait for it to complete before proceeding.

If not shown, skip to step 5.

## Step 5: Work Selection (ALWAYS RUNS)

Run `/xp-work-selection`. This handles all user interaction for the session:
- Retro Try item review (adopt/defer/drop)
- Open question triage
- Sprint story selection (or session goal collection if no sprint)

**If the user chose free session in step 2**, tell the work-selection skill to collect session goals only — skip story selection even if a sprint is active.

Wait for it to complete before proceeding.

## Step 6: Housekeeping (ALWAYS RUNS)

Invoke the `xp-housekeeper` agent directly via the Agent tool (`subagent_type=xp-agents:xp-housekeeper`). This is mandatory — it curates the four-pillar SMM (Intent, Constraints, Risks, Wisdom). The SubagentStart hook writes `${SMM_DIR}/.curation-input.json` from `materialize.prepare_curation_data` and injects the path plus any Session Work Selection block (adopted/deferred/dropped retro Tries + session goals). The agent reads the curation input, mutates the SMM via `smm_cli.py` item-level commands, and finalizes with `complete-curation`. **Kickoff is not complete until housekeeping finishes.**

**Do NOT run housekeeping in the background.** Wait for the subagent to complete before proceeding to step 7.

If the user says "skip" at any earlier step, still run housekeeping.

## Step 7: Render the curated SMM

After the housekeeper completes, render the curated SMM:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py --smm-dir <SMM_DIR> render
```

Output the render CLI's stdout to the user, followed by the change summary the housekeeper agent returned (items added/removed/promoted/resolved, health warnings). The process guide is injected separately into your context via a PostToolUse hook — you do not need to display it.

Kickoff is complete. **Do NOT stop.**

**If stories were selected in step 5**, follow the plan cycle: enter plan mode, run `/xp-review-plan` after exiting, then run `/xp-assign` — it reads the plan's steps to decide execution mode (solo or worktree subagents). This works in both sprint and free sessions.

**If no sprint is active or the user chose free session**, begin working on the session goals.
