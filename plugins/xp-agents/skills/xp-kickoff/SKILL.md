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

**You MUST complete ALL steps below in order. Do NOT stop after any single step. Do NOT start working on the user's goal until ALL steps are done. Housekeeping (step 5) MUST always run — it is not optional. Only after housekeeping completes should you begin working on the session goals.**

## Step 1: Retrospective (if RETRO_NEEDED)

If the preload shows "RETRO_NEEDED", invoke the `/xp-run-retrospective` skill immediately. **Do NOT analyze events yourself — the skill runs a dedicated subagent that does the analysis.** Just invoke it and wait for the result.

**Show the full retrospective output to the user** — do not summarize it.

Proceed to step 2.

## Step 2: Product Spec (if NEEDS_PRODUCT_SPEC)

If the preload shows "NEEDS_PRODUCT_SPEC", invoke `/xp-product-spec` to create a product specification. Wait for it to complete before proceeding.

If not shown, skip to step 3.

## Step 3: Sprint Start (if NEEDS_SPRINT)

If the preload shows "NEEDS_SPRINT", invoke `/xp-sprint-start` to plan a sprint with user stories. Wait for it to complete before proceeding.

If not shown, skip to step 4.

## Step 4: Work Selection (ALWAYS RUNS)

Run `/xp-work-selection`. This handles all user interaction for the session:
- Retro Try item review (adopt/defer/drop)
- Open question triage
- Sprint story selection (or session goal collection if no sprint)

Wait for it to complete before proceeding.

## Step 5: Housekeeping (ALWAYS RUNS)

Run `/xp-housekeeping`. This is mandatory — it curates the five-pillar SMM (Intent, Constraints, Risks, Wisdom, Sprint) via a forked subagent. The curated SMM, XP values, and process guide are injected automatically when housekeeping completes. **Kickoff is not complete until housekeeping finishes.**

If the user says "skip" at any earlier step, still run housekeeping.

## Step 6: Complete

Kickoff is complete. **Do NOT stop.**

**If stories were selected in step 4**, decide how to proceed:
- **1 story** → Enter plan mode and begin planning it immediately.
- **2+ independent stories** (no dependencies between them) → Enter plan mode to plan the work, then run `/xp-spawn-team` to get team sizing and spawn instructions for parallel execution.
- **2+ stories with dependencies** → Enter plan mode and plan the first story (by dependency order). The dependent stories will be picked up after.

**If no sprint is active**, begin working on the session goals.
