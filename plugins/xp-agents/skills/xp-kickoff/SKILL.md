---
name: xp-kickoff
description: >-
  Session start orchestrator. Sequences retrospective, sprint setup,
  work selection, and housekeeping. Use at the start of every session.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh`

# Session Kickoff

The session status above was preloaded automatically.

**You MUST complete ALL steps below in order. Do NOT stop after any single step. Do NOT start working on the user's goal until ALL steps are done. Housekeeping (step 6) MUST always run — it is not optional. Only after housekeeping completes should you begin working on the session goals.**

## Step 1: Retrospective (if RETRO_NEEDED)

If the preload shows **RETRO_NEEDED**, invoke the `/xp-run-retrospective` skill immediately. The session retro handles both regular sessions and sprint completions — when a sprint just ended, the retro input includes sprint sizing metrics automatically.

**Do NOT analyze events yourself — the skill runs a dedicated subagent that does the analysis.** Just invoke it and wait for the result.

**Terminal action of this step: output the full retrospective verbatim before calling any other tool.** The subagent result is NOT visible to the user — if you skip ahead, the retro is lost. Do not summarize.

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

Run `/xp-housekeeping`. This is mandatory — it curates the four-pillar SMM (Intent, Constraints, Risks, Wisdom) via a forked subagent. **Kickoff is not complete until housekeeping finishes.**

**Do NOT run housekeeping in the background.** Wait for the subagent to complete before proceeding to step 7. The subagent returns the rendered SMM and a summary of changes — the subagent result is NOT visible to the user — you must output both as text in your response.

If the user says "skip" at any earlier step, still run housekeeping.

## Step 7: Complete

**Output both the rendered SMM and the housekeeping summary as text in your response** (the subagent result is NOT visible to the user). The housekeeper subagent returns the full curated SMM (rendered markdown) followed by a change summary (items added, removed, promoted, resolved, health warnings). You must output both so the user can see the current state and what changed. The process guide is injected separately into your context via a PostToolUse hook — you do not need to display it.

Kickoff is complete. **Do NOT stop.**

**If stories were selected in step 5**, follow the plan cycle: enter plan mode, run `/xp-review-plan` after exiting, then run `/xp-assign` — it reads the plan's steps to decide execution mode (solo or worktree subagents). This works in both sprint and free sessions.

**If no sprint is active or the user chose free session**, begin working on the session goals.
