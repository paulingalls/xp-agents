---
name: xp-housekeeping
description: >-
  Lifecycle triage for open items. Reviews goals, concerns, draft decisions,
  and technical debt. Asks user for status and records resolutions.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`${CLAUDE_SKILL_DIR}/scripts/check_open_items.sh`

# Housekeeping — Lifecycle Triage

The open items above were preloaded automatically. Review each category and ask the user for status updates.

## 1. Goals Review

For each open goal listed above, ask the user:
- "Is this goal still active, or has it been completed/abandoned?"

Use `AskUserQuestion` to present all open goals at once with options per goal.

For each completed goal, record the resolution:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-housekeeping" \
  --content "Goal completed: <goal description>" \
  --working-on '[]' \
  --metadata '{"resolves": ["<goal-event-id>"]}'
```

## 2. Concern Triage

For each unresolved concern, ask the user:
- "Is this concern still relevant, or has it been addressed?"

For resolved concerns:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-housekeeping" \
  --content "Concern resolved: <concern description>" \
  --working-on '[]' \
  --metadata '{"resolves": ["<concern-event-id>"]}'
```

## 3. Draft Decisions

For each draft decision, ask the user:
- "Should this decision be confirmed as an architectural decision, or rejected?"

For confirmed decisions, record a new non-draft decision:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "decision" \
  --agent "xp-housekeeping" \
  --content "<decision content>" \
  --topic "<same topic>" \
  --references '["<draft-decision-id>"]'
```

For rejected drafts:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-housekeeping" \
  --content "Draft rejected: <decision description>" \
  --working-on '[]' \
  --metadata '{"resolves": ["<draft-decision-id>"]}'
```

## 4. Debt Check

For each open debt item, ask the user:
- "Has this technical debt been fixed?"

For fixed debt:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-housekeeping" \
  --content "Debt fixed: <debt description>" \
  --working-on '[]' \
  --metadata '{"resolves": ["<debt-event-id>"]}'
```

## Guidelines

- Be concise. Present items in batches, not one at a time.
- If the user says "skip" or "later", move on. Items persist until resolved.
- If there are no open items in a category, skip it silently.
- Extract the event IDs from the `[short-id]` markers in the SMM output. Use the full event ID from the events.jsonl if needed.

## 5. Load Session Context

After completing all triage steps, load the full context:

1. Run: `${CLAUDE_SKILL_DIR}/scripts/load_context.sh`
2. Read the file at the SMM_FILE path from the output
3. Read the file at the GUIDE_FILE path from the output

This ensures the full Shared Mental Model and Behavioral Guide are in your conversation context.
