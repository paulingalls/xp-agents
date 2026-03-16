---
name: xp-goal-collection
description: >-
  Collect project goals from the user. Use at first session start when
  no goals have been recorded yet, or when the user wants to update goals.
allowed-tools:
  - Bash(*/append.sh *)
---

!`${CLAUDE_SKILL_DIR}/scripts/check_goals.sh`

# Goal Collection

The goal status above was preloaded automatically.

## If Goals: NONE RECORDED

1. Ask the user for their project goals using `AskUserQuestion`:
   - "What are the main goals for this project? (e.g., 'Ship MVP by March', 'Migrate to new API')"
2. If the user provides goals, record each as a `goal` event:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
     --type "goal" \
     --agent "xp-goal-collection" \
     --content "Goal description from user"
   ```
3. If the user declines or skips, move on. Goal collection is non-blocking.

## If Goals: PRESENT

Report briefly that goals already exist. If the user invoked this skill manually, ask if they want to add or update goals.

## Guidelines

- Be respectful of the user's time — keep it concise.
- If the user provides multiple goals in one response, record each as a separate event.
- If the user declines to answer, move on gracefully.
