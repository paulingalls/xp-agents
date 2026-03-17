---
name: xp-session-review
description: >-
  Session start orchestrator. Sequences retrospective, goal collection, and
  housekeeping in priority order. Use at the start of every session.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh`

# Session Review

The session status above was preloaded automatically.

Complete the following actions **in order**, skipping any marked as not needed:

## 1. Retrospective (if RETRO_NEEDED)

Run `/xp-retrospective` to analyze the previous session.

If the preload shows "RETRO_NEEDED", invoke the retrospective skill now. Wait for it to complete before proceeding.

If not needed, skip to step 2.

## 2. Goal Collection (if GOALS_NEEDED)

Run `/xp-goal-collection` to collect project goals from the user.

If the preload shows "GOALS_NEEDED", invoke the goal collection skill now. Wait for it to complete before proceeding.

If not needed, skip to step 3.

## 3. Housekeeping (if HOUSEKEEPING_NEEDED)

Run `/xp-housekeeping` to review open concerns, draft decisions, and technical debt.

If the preload shows "HOUSEKEEPING_NEEDED", invoke the housekeeping skill now.

If not needed, skip to step 4.

## 4. Materialize Fresh SMM and Clear Gate

After all actions are complete, materialize the fresh SMM and clear the session review gate:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/materialize.py
SMM_DIR=$(${CLAUDE_PLUGIN_ROOT}/smm/init.sh)
rm -f "$SMM_DIR/.needs-session-review"
```

Then read and summarize the updated `SHARED_MENTAL_MODEL.md` for the user.

## If NONE Needed

Report "Session review complete — no actions needed." and proceed with the user's request.

## Guidelines

- Complete each step before moving to the next.
- If the user says "skip" at any step, move to the next one.
- After all steps complete, the SMM is fresh and work can begin.
