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

!`${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh`

# Session Kickoff

The session status above was preloaded automatically.

**You MUST complete ALL steps below in order. Do NOT stop after any single step. Do NOT start working on the user's goal until ALL steps are done. Housekeeping (step 4) MUST always run — it is not optional. Only after housekeeping completes should you begin working on the session goals.**

## Step 1: Retrospective (if RETRO_NEEDED)

If the preload shows "RETRO_NEEDED", run `/xp-retrospective` now. Wait for it to complete, then proceed to step 2.

If not needed, proceed to step 2.

## Step 2: Goal Collection

Run `/xp-goal-collection`. This always runs — it shows existing goals and asks for session goals. After it completes, proceed to step 3.

## Step 3: Question Triage (if QUESTIONS_NEEDED)

If the preload shows "QUESTIONS_NEEDED", run `/xp-question-triage` now. Wait for it to complete, then proceed to step 4.

If not needed, proceed to step 4.

## Step 4: Housekeeping (ALWAYS RUNS)

Run `/xp-housekeeping`. This is mandatory — it curates the four-pillar SMM (Intent, Constraints, Risks, Wisdom) and triggers the behavioral guide injection. **Kickoff is not complete until housekeeping finishes.**

If the user says "skip" at any earlier step, still proceed to the next step. Housekeeping must always run.
