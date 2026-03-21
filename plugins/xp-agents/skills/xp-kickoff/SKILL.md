---
name: xp-kickoff
description: >-
  Session start orchestrator. Sequences retrospective, goal collection, and
  housekeeping in priority order. Use at the start of every session.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh`

# Session Kickoff

The session status above was preloaded automatically.

**Before starting:** Run `ToolSearch` with query `"select:Skill"` to load the Skill tool schema.

**You MUST complete ALL steps below in order. Do NOT stop after any single step. Do NOT start working on the user's goal until ALL steps are done. Housekeeping (step 5) MUST always run — it is not optional. Only after housekeeping completes should you begin working on the session goals.**

## Step 1: Retrospective (if RETRO_NEEDED)

If the preload shows "RETRO_NEEDED", invoke the `/xp-run-retrospective` skill immediately. **Do NOT analyze events yourself — the skill runs a dedicated subagent that does the analysis.** Just invoke it and wait for the result.

**Show the full retrospective output to the user** — do not summarize it.

Proceed to step 2.

## Step 2: Review Previous Try Items

If the preload shows Try items under "PREVIOUS_TRIES", briefly review each one with the user. For each Try item, note whether it was:
- **Adopted** — became a practice this session
- **Deferred** — still relevant, carry forward
- **Dropped** — no longer relevant

Proceed to step 3.

## Step 3: Question Triage (if QUESTIONS_NEEDED)

If the preload shows "QUESTIONS_NEEDED", run `/xp-question-triage` now. Resolve questions first — answers may inform goals.

Proceed to step 4.

## Step 4: Goal Collection

Run `/xp-goal-collection`. This always runs — it shows existing goals and asks for session goals. After it completes, proceed to step 5.

## Step 5: Housekeeping (ALWAYS RUNS)

Run `/xp-housekeeping`. This is mandatory — it curates the four-pillar SMM (Intent, Constraints, Risks, Wisdom) and triggers the behavioral guide injection. **Kickoff is not complete until housekeeping finishes.**

If the user says "skip" at any earlier step, still proceed to the next step. Housekeeping must always run.
