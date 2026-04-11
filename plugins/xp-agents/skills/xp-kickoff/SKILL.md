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

## Step 1: Retrospective (if SPRINT_RETRO_NEEDED or RETRO_NEEDED)

The preload reports exactly one of these flags (or neither):

- **SPRINT_RETRO_NEEDED** — the previous session ended a sprint without retrospecting it. Invoke the `/xp-run-sprint-retro` skill immediately. The sprint retrospective covers the full sprint instead of the regular session retro.
- **RETRO_NEEDED** — unanalyzed events from previous sessions. Invoke the `/xp-run-retrospective` skill immediately.

**Do NOT analyze events yourself — both skills run dedicated subagents that do the analysis.** Just invoke the right one and wait for the result.

**The subagent result is NOT visible to the user** — you must output the full retrospective as text in your response. Do not summarize it.

Proceed to step 2.

## Step 2: Session mode (ALWAYS)

Ask the user via AskUserQuestion: **"Free session or Sprint session?"**

- **Free session** — for brainstorming, Q&A, bug fixes, or any work that doesn't need sprint scaffolding.
- **Sprint session** — for planned work with product spec, sprint stories, and acceptance criteria.

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

Run `/xp-housekeeping`. This is mandatory — it curates the five-pillar SMM (Intent, Constraints, Risks, Wisdom, Sprint) via a forked subagent. The curated SMM, XP values, and process guide are injected automatically when housekeeping completes. **Kickoff is not complete until housekeeping finishes.**

**Do NOT run housekeeping in the background.** Wait for the subagent to complete before proceeding to step 7. The subagent returns a summary of what it changed — the subagent result is NOT visible to the user — you must output this summary as text in your response so they know what was added, removed, or resolved in the SMM.

If the user says "skip" at any earlier step, still run housekeeping.

## Step 7: Complete

**Output the housekeeping summary as text in your response** (the subagent result is NOT visible to the user). The housekeeper subagent returns a concise summary of SMM changes (items added, removed, promoted, resolved, health warnings). You must output this so the user can see what changed. Do not skip or summarize it further.

Kickoff is complete. **Do NOT stop.**

**If stories were selected in step 5**, decide how to proceed:
- **1 story** → Enter plan mode and begin planning it immediately.
- **2+ independent stories** (no dependencies between them) → Enter plan mode to plan the work, then run `/xp-spawn-team` to get team sizing and spawn instructions for parallel execution.
- **2+ stories with dependencies** → Enter plan mode and plan the first story (by dependency order). The dependent stories will be picked up after.

**If no sprint is active or the user chose free session**, begin working on the session goals.
