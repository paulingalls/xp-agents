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

Complete the following actions **in order**, skipping any marked as not needed:

## 1. Retrospective (if RETRO_NEEDED)

Run `/xp-retrospective` to analyze the previous session.

If the preload shows "RETRO_NEEDED", invoke the retrospective skill now. Wait for it to complete before proceeding.

If not needed, skip to step 2.

## 2. Goal Collection

Run `/xp-goal-collection` to review goals and collect any new ones from the user.

The preload shows current goals under "GOALS_REVIEW". Always invoke the goal collection skill — it shows existing goals and asks for session goals. Quick to skip if no new goals.

## 3. Housekeeping

Run `/xp-housekeeping` to curate Intent, Constraints, Risks, and Wisdom pillars.

Housekeeping always runs as the final step. It triages open items across all four pillars. This also ensures the PostToolUse:Skill hook fires to inject the SMM and behavioral guide.

## Guidelines

- Complete each step before moving to the next.
- If the user says "skip" at any step, move to the next one.
- The PostToolUse:Skill hook will automatically materialize the SMM and inject it (along with the behavioral guide) when `/xp-housekeeping` completes. No manual materialize step needed.
