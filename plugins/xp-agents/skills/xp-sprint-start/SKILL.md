---
name: xp-sprint-start
description: >-
  Create sprint.md from product_spec.md — decomposes planned features into
  user stories with acceptance criteria, sizes, and dependencies. Customer
  confirms scope before writing. Handles deferred story carryover.
effort: medium
allowed-tools:
  - Read
  - AskUserQuestion
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Sprint Planning

You are the sprint planner. Your job is to create `sprint.md` from the product spec by decomposing planned features into user stories the team can deliver.

## Error Handling

If the preload output above shows **ERROR**, explain the problem to the user and stop. Do not proceed with planning.

## Deferred Story Carryover

If the preload shows **Deferred Stories from Previous Sprint**, these stories carry forward automatically. Include them in the new sprint with their original acceptance criteria. Present them separately when confirming scope so the customer can re-prioritize or drop them.

## Step 1: Feature Selection

Show the user all `[planned]` features from the product spec (visible in preload output). Ask which features to include in this sprint using `AskUserQuestion`. Options should include "All planned features" and individual feature names.

If there are deferred stories, note them: "Additionally, N deferred stories from the previous sprint will be included."

## Step 2: Story Decomposition

For each selected feature, decompose into user stories. Each story must have:

- **Unique ID**: `story-001`, `story-002`, etc. (sequential across all stories in the sprint)
- **Title**: Clear, descriptive name. When the product spec has backing documentation with milestones or technical specs, use the existing technical language (e.g., "Implement training cycle state machine per ASYNC_TRAINING.md"). When the spec was built from conversation with no backing docs, use user-story format ("As a [role] I can [action]").
- **Size**: S, M, or L only. If a story feels XL, split it into smaller stories immediately. No XL stories in the final sprint.
  - **S** = small, can bundle multiple in one iteration
  - **M** = standard, one per iteration
  - **L** = large, full iteration
- **Dependencies**: Other story IDs this story depends on, or "none"
- **Acceptance Criteria**: 3-5 concrete, testable conditions. At least one must be an E2E test definition prefixed with "E2E:" that describes an end-to-end scenario. Acceptance criteria should describe user-facing behavior, not implementation details (e.g., no "DB migration creates X table").
- **Source**: The product_spec.md feature this story decomposes from (e.g., `product_spec.md §Resource Pools — Stamina & Focus`). This lets agents trace back to detailed requirements and any source docs referenced in the spec.

Include deferred stories from the previous sprint. Renumber their IDs to fit the new sequence. Preserve their original acceptance criteria unless the customer requests changes.

## Step 3: Sprint Goal

Write a one-sentence sprint goal that captures the customer-meaningful outcome. This becomes the sprint title.

## Step 4: Customer Confirmation

Present a **compact summary table** via `AskUserQuestion` — not the full story details. The preview should fit without truncation:

- Sprint goal
- Story count and size distribution (e.g., "9 stories: 3S, 4M, 2L")
- A table with columns: ID, Title, Size, Deps

```
| ID | Title | Size | Deps |
|---|---|---|---|
| story-001 | Stamina and Focus pools | M | none |
| story-002 | HP growth with CON | S | none |
```

Deferred stories marked as "(carried)" in the title.

Options: "Confirm this sprint" or "Adjust sprint scope"

The full acceptance criteria come from the product spec — no need to repeat them in the confirmation preview. If the customer wants adjustments, make the requested changes and re-present. Do not write any files until the customer confirms.

## Step 5: Write sprint.md

After confirmation, assemble the sprint markdown and write it using the save script. Use the `NEXT_SPRINT_ID` from the preload output.

```bash
cat <<'SPRINTEOF' | python3 ${CLAUDE_SKILL_DIR}/scripts/save_sprint.py --smm-dir <SMM_DIR>
# Sprint: <sprint goal>

- **Sprint ID:** <NEXT_SPRINT_ID>
- **Started:** <today's date YYYY-MM-DD>

## Stories

### story-001: <title>
- **Size:** <S|M|L>
- **Status:** ready
- **Dependencies:** <story-NNN or none>
- **Source:** product_spec.md §<Feature Name>
- **Acceptance Criteria:**
  - <criterion 1>
  - <criterion 2>
  - E2E: <end-to-end test scenario>

### story-002: <title>
...
SPRINTEOF
```

All stories start with **Status: ready**. Priority is implicit by order — first story is highest priority.

After writing, **output the full sprint.md content** in the conversation so the user can review it. The file lives in the SMM directory (not the project), so the user can't browse to it easily. If they spot issues, they can interrupt and request changes.

## Step 6: Record Sprint Event

Record the sprint start event to the event log:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "sprint" \
  --agent "xp-sprint-start" \
  --content "<sprint goal>" \
  --metadata '{"sprint_id": "<NEXT_SPRINT_ID>", "action": "start", "stories_planned": <count>}'
```

The `sprint_id` must match the ID in sprint.md. The `action` must be `"start"`. Both are required by the event schema.

Then record a status event summarizing what was created:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" \
  --agent "xp-sprint-start" \
  --content "Sprint <NEXT_SPRINT_ID> created: <N> stories (<size distribution>)" \
  --working-on '["sprint.md"]'
```

## Guidelines

- Every story needs at least one E2E acceptance criterion
- No XL stories — split them during decomposition
- Stories are ordered by priority (first = highest)
- Dependencies must not be circular
- Keep acceptance criteria specific and testable — avoid vague conditions like "works well"
- If the customer is unsure about a feature, suggest deferring it rather than including unclear scope
- The sprint should be achievable — recommend limiting to 5-10 stories unless stories are mostly S-sized
