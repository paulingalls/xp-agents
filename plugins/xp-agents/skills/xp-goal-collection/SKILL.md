---
name: xp-goal-collection
description: >-
  Collect project goals from the user. Use at every session start to review
  existing goals and add new ones, or when the user wants to update goals.
effort: low
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/check_goals.sh`

# Goal Collection

The current goals above were preloaded automatically.

## Flow

1. Show the existing goals from the preload (already displayed above).
2. Ask the user using `AskUserQuestion`:
   - "Any goals for this session?" with options like "Add goals", "No new goals"
3. If the user wants to add goals, ask what they are and record each as a `goal` event:
   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
     --type "goal" \
     --agent "xp-goal-collection" \
     --content "Goal description from user"
   ```
4. If the user says no or skips, move on immediately. Goal collection is non-blocking.

## Guidelines

- Be respectful of the user's time — keep it concise.
- If the user provides multiple goals in one response, record each as a separate event.
- If the user declines to answer, move on gracefully.
- Goals can be long-term ("Ship the plugin") or session-specific ("Fix the compaction bug today").
