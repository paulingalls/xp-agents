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

**You MUST complete ALL steps below in order. Do NOT stop after any single step. Do NOT start working on the user's goal until ALL steps are done. Housekeeping (step 6) MUST always run — it is not optional. Only begin session work after housekeeping completes.**

## Step 1: Retrospective (ALWAYS)

Invoke the `xp-retrospective` agent via the Agent tool (`subagent_type=xp-agents:xp-retrospective`). The agent handles both populated and empty `.retro-input.json` — on a fresh project with no prior session_end, it emits a seed retrospective (Keep around adopting XP, Try as skill suggestions, no Fix). Do NOT gate this step on the existence of `.retro-input.json`; the agent owns that branch.

After it completes, render the latest retrospective:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/retro_cli.py --smm-dir <SMM_DIR> render
```

Output the render CLI's stdout to the user before continuing.

## Step 2: Session mode (ALWAYS)

Ask the user via AskUserQuestion: **"Free session or Sprint session?"**

- **Free session** — for brainstorming, Q&A, bug fixes, or any work that doesn't need sprint scaffolding.
- **Sprint session** — for planned work with product spec, sprint stories, and acceptance criteria.

Record the session mode as a goal event:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "goal" --agent "xp-kickoff" \
  --content "Free session" # or "Sprint session: <sprint-id>"
```

If the user chooses **free session**: skip steps 3 and 4, jump directly to step 5 (Work Selection). In step 5, collect freeform session goals only — do NOT show sprint stories or prompt for story selection, even if a sprint exists.

If the user chooses **sprint session**: proceed to step 3.

## Step 2.4: Stage 2 floor migration prompt (ALWAYS, every kickoff)

This step runs at every kickoff regardless of the session mode chosen in Step 2 — the Stage 2 floor matters for both free and sprint sessions.

Read the branching stage:
```bash
STAGE=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage)
```

If `STAGE >= 2`, **skip this step**. Otherwise invoke the
`xp-stage-migration` skill via the Skill tool
(`skill=xp-agents:xp-stage-migration`) — it handles the dismissal check,
the migrate/continue prompt, and the dismissal record. After it returns,
proceed to Step 2.5.

## Step 2.5: Auto-create free branch on protected (free sessions only)

If the user chose **free session** AND the branching stage is `>= 2` AND the current branch is a protected branch (`main` or `master`), create and check out a fresh free branch.

Read the stage:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage
```

If stage is `0`, **skip this step**. If the current branch is already non-protected, **skip this step** — do not nest branches.

Otherwise, create the free branch with a slug derived from the user's session goal (first 3-4 words, slugified):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  create-free --cwd . --slug "<session-goal-slug>"
```

The CLI returns `<user>/free-YYYY-MM-DD-<slug>` and checks it out. Tell the user which branch was created.

## Step 2.6: Orphan free-branch triage (ALWAYS)

If the preload shows **ORPHAN_FREE_BRANCHES**, ask via `AskUserQuestion` for each: **merge / keep / delete?**

- **merge** — invoke `/xp-free-close` against that branch (check it out first if needed).
- **keep** — leave the branch alone; it will reappear at the next kickoff.
- **delete** — `branching.py delete --branch <name>`. Do not auto-delete branches with commits ahead of primary.

## Step 2.7: Orphan story-branch triage (ALWAYS)

If the preload shows **ORPHAN_STORY_BRANCHES**, ask via `AskUserQuestion` for each: **merge / keep / delete?**

- **merge** — `branching.py merge-branch --cwd . --branch <name>`, then `branching.py delete --cwd . --branch <name>`.
- **keep** — leave the branch alone; it will reappear at the next kickoff.
- **delete** — `branching.py delete --cwd . --branch <name>`. Do not auto-delete branches with commits ahead of base.

## Step 3: System Context and Execution Plan (if NEEDS_SYSTEM_CONTEXT or NEEDS_EXECUTION_PLAN)

If the preload shows "NEEDS_SYSTEM_CONTEXT" and this is a sprint session, invoke `/xp-system-context`. Wait for it to complete.

If the preload shows "NEEDS_EXECUTION_PLAN", first `Read` the SMM file at `<SMM_DIR>/shared_mental_model.json` for context. Then invoke `/xp-plan`. Wait for it to complete.

If neither is shown, skip to step 4.

## Step 4: Sprint Start (if NEEDS_SPRINT)

If the preload shows "NEEDS_SPRINT" and you haven't read the SMM in step 3, `Read` `<SMM_DIR>/shared_mental_model.json` first. Then invoke `/xp-sprint-start`. Wait for it to complete.

If not shown, skip to step 5.

## Step 5: Work Selection (ALWAYS RUNS)

Run `/xp-work-selection`. This handles all user interaction for the session: retro Try item review, open question triage, sprint story selection (or session goal collection if no sprint).

**If the user chose free session in step 2**, tell the work-selection skill to collect session goals only — skip story selection even if a sprint is active.

Wait for it to complete.

## Step 6: Housekeeping (ALWAYS RUNS)

Invoke the `xp-housekeeper` agent via the Agent tool (`subagent_type=xp-agents:xp-housekeeper`). This is mandatory — it curates the four-pillar SMM (Intent, Constraints, Risks, Wisdom). **Kickoff is not complete until housekeeping finishes.**

**Do NOT run housekeeping in the background.** Wait for the subagent to complete before proceeding to step 7.

If the user said "skip" at any earlier step, still run housekeeping.

## Step 7: Render the curated SMM

After housekeeping completes, render:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py --smm-dir <SMM_DIR> render
```

Output the render CLI's stdout to the user, followed by the change summary the housekeeper agent returned (items added/removed/promoted/resolved, health warnings).

Kickoff is complete. **Do NOT stop.**

**If stories were selected in step 5**, follow the plan cycle: enter plan mode, run `/xp-review-plan` after exiting, then run `/xp-assign`.

**If no sprint is active or the user chose free session**, begin working on the session goals.
