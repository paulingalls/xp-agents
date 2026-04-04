---
name: xp-kickoff
description: >-
  Session start orchestrator. Sequences retrospective, sprint setup,
  housekeeping, and story selection. Use at the start of every session.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh`

# Session Kickoff

The session status above was preloaded automatically.

**Before starting:** Run `ToolSearch` with query `"select:Skill,Agent"` to load the Skill and Agent tool schemas. Both are needed — skills invoke `/xp-run-retrospective` and `/xp-review-plan`, which delegate to plugin subagents via the Agent tool.

**You MUST complete ALL steps below in order. Do NOT stop after any single step. Do NOT start working on the user's goal until ALL steps are done. Housekeeping MUST always run — it is not optional. Only after ALL steps complete should you begin working.**

## Step 1: Retrospective (if RETRO_NEEDED)

If the preload shows "RETRO_NEEDED", invoke the `/xp-run-retrospective` skill immediately. **Do NOT analyze events yourself — the skill runs a dedicated subagent that does the analysis.** Just invoke it and wait for the result.

**Show the full retrospective output to the user** — do not summarize it.

Proceed to step 2.

## Step 2: Product Spec Check (if NEEDS_PRODUCT_SPEC)

If the preload shows "NEEDS_PRODUCT_SPEC", invoke `/xp-product-spec` to create a product specification. Wait for it to complete before proceeding.

If not shown, skip to step 3.

## Step 3: Sprint Check (if NEEDS_SPRINT)

If the preload shows "NEEDS_SPRINT", invoke `/xp-sprint-start` to plan a sprint with user stories. Wait for it to complete before proceeding.

If not shown, skip to step 4.

## Step 4: Housekeeping (ALWAYS RUNS)

Run `/xp-housekeeping`. This is mandatory — it curates the four-pillar SMM (Intent, Constraints, Risks, Wisdom) and triggers the behavioral guide injection. **Kickoff is not complete until housekeeping finishes.**

If the user says "skip" at any earlier step, still run housekeeping.

## Step 5: Story Selection OR Goal Collection

**If the preload shows "SPRINT_ACTIVE" OR if Step 3 just created a sprint**, do story selection. If Step 3 created the sprint, re-read sprint.md from SMM_DIR to get the ready stories (the preload data is stale).

**Story selection** (sprint with ready stories):

1. Show the ready stories listed in the preload output to the user.
2. Ask the user via `AskUserQuestion`: "Which stories should we work on this iteration?" Offer options: individual story IDs (e.g., "story-001, story-003"), or "all ready stories". If the user has questions about any stories, resolve them inline here.
3. Once the user confirms, use `Read` to read the full `sprint.md` from the SMM directory (path shown in preload as `SMM_DIR`).
4. In the content, change each selected story's `**Status:** ready` to `**Status:** in-progress`. Leave unselected stories unchanged.
5. Write the updated content via save_sprint.py:
   ```bash
   cat <<'SPRINTEOF' | python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-sprint-start/scripts/save_sprint.py --smm-dir <SMM_DIR>
   <full updated sprint.md content>
   SPRINTEOF
   ```
6. Record a status event:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
     --type "status" --agent "xp-kickoff" \
     --content "Story selection: marked N stories in-progress" \
     --working-on '[]'
   ```

**If no SPRINT_ACTIVE** (no sprint, no ready stories, or first-time project):

1. If the preload shows "QUESTIONS_NEEDED", run `/xp-question-triage` to handle open questions, assumptions, and previous retro Try items.
2. Run `/xp-goal-collection` to show existing goals and ask for session goals.

## Step 6: Complete

Kickoff is complete. **Do NOT stop.** Enter plan mode and begin planning the first selected story immediately. If no sprint is active, begin working on the session goals.
