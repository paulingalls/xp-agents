---
name: xp-kickoff
description: >-
  Session start orchestrator. Sequences retrospective, goal collection, and
  housekeeping in priority order. Use at the start of every session.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(cat *| CLAUDE_PLUGIN_DATA=* python3 */save_retrospective.py)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh`

# Session Kickoff

The session status above was preloaded automatically.

**You MUST complete ALL steps below in order. Do NOT stop after any single step. Do NOT start working on the user's goal until ALL steps are done. Housekeeping (step 5) MUST always run — it is not optional. Only after housekeeping completes should you begin working on the session goals.**

## Step 1: Retrospective (if RETRO_NEEDED)

If the preload shows "RETRO_NEEDED", invoke the `/xp-run-retrospective` skill immediately. **Do NOT analyze events yourself — the skill runs a dedicated subagent that does the analysis.** Just invoke it and wait for the result.

**Show the full retrospective output to the user** — Keep, Fix, and Try items with all details. Do not summarize it.

The retrospective subagent saves its own results via `save_retrospective.py`. **Do NOT use the Write tool to save retrospective files yourself.**

After the subagent returns, verify the retrospective was saved by checking for a `retrospective` event at the end of the event log (use the SMM_DIR from the preload output above):

```bash
tail -5 <SMM_DIR>/events.jsonl | grep '"type": "retrospective"'
```

If no retrospective event is found, the subagent failed to save — run the save yourself as a fallback:

```bash
cat <<'RETRO_JSON' | CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" python3 ${CLAUDE_PLUGIN_ROOT}/scripts/save_retrospective.py
{
  "keep": [<keep items from the subagent's output>],
  "fix": [<fix items from the subagent's output>],
  "try": [<try items from the subagent's output>]
}
RETRO_JSON
```

If not needed, proceed to step 2.

## Step 2: Review Previous Try Items

If the preload shows Try items under "PREVIOUS_TRIES", briefly review each one with the user. For each Try item, note whether it was:
- **Adopted** — became a practice this session
- **Deferred** — still relevant, carry forward
- **Dropped** — no longer relevant

This takes 1-2 minutes. If there are no Try items, skip to step 3.

## Step 3: Question Triage (if QUESTIONS_NEEDED)

If the preload shows "QUESTIONS_NEEDED", run `/xp-question-triage` now. Resolve questions first — answers may inform goals. Wait for it to complete, then proceed to step 4.

If not needed, proceed to step 4.

## Step 4: Goal Collection

Run `/xp-goal-collection`. This always runs — it shows existing goals and asks for session goals. After it completes, proceed to step 5.

## Step 5: Housekeeping (ALWAYS RUNS)

Run `/xp-housekeeping`. This is mandatory — it curates the four-pillar SMM (Intent, Constraints, Risks, Wisdom) and triggers the behavioral guide injection. **Kickoff is not complete until housekeeping finishes.**

If the user says "skip" at any earlier step, still proceed to the next step. Housekeeping must always run.
