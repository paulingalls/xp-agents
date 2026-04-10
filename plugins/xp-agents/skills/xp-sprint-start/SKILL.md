---
name: xp-sprint-start
description: >-
  Create sprint.md from an execution plan milestone or product spec.
  Decomposes milestones into context-rich stories with file domains,
  interface contracts, and inlined design context. Deep codebase dive
  identifies story boundaries. Customer confirms scope before writing.
effort: medium
allowed-tools:
  - Read
  - Glob
  - Grep
  - AskUserQuestion
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Sprint Planning

You are the sprint planner. Your job is to create `sprint.md` by decomposing a milestone from `execution_plan.md` into context-rich stories the team can deliver — including in parallel via subagents.

## Error Handling

If the preload output above shows **ERROR**, explain the problem to the user and stop. Do not proceed with planning.

## Deferred Story Carryover

If the preload shows **Deferred Stories from Previous Sprint**, these stories carry forward. Include them in the new sprint with their original acceptance criteria. Present them separately when confirming scope.

---

## Milestone-Based Planning (execution_plan.md)

Use this flow when `EXECUTION_PLAN=<path>` is shown in the preload.

### Step 1: Milestone Selection

Read the execution plan using `Read`. Show the user all `[planned]` milestones with their goals. Ask which milestone to include in this sprint using `AskUserQuestion`.

One sprint = one milestone. If a milestone has >8 change zone files, suggest splitting it before proceeding.

### Step 2: Deep Codebase Dive

This is the key step that makes stories self-contained for parallel execution.

For the selected milestone, read its **Change Zones** and **Impact Zones**:
1. Use `Read` to examine each file in the change zones. Understand current structure, key functions, interfaces.
2. Use `Read` on impact zone files to understand dependency relationships.
3. Use `Glob` and `Grep` to find related files not listed in the milestone (tests, imports).

From this analysis, identify:
- **Natural story boundaries** — cohesive groups of files that can be changed independently
- **Shared interfaces** — functions, types, or contracts that multiple stories will touch
- **File domains** — which files each story exclusively owns (no overlap between stories)

### Step 3: Story Decomposition

For each story, produce the enhanced format:

- **Unique ID**: `story-001`, `story-002`, etc.
- **Title**: Clear, descriptive name using the milestone's technical language.
- **Size**: S, M, or L. If XL, split immediately.
- **Dependencies**: Other story IDs, or "none".
- **Milestone**: `execution_plan.md §Milestone N` — traces back to the milestone.
- **Design Sources**: Direct references to the original design documents (from the milestone's Sources field) with section pointers. Preserves the connection to the full design work.

Then the enriched sections:

- **Context**: 2+ sentences of inlined design context. Synthesize from the milestone's Design Details + what you learned in the codebase dive. This is NOT a pointer — it's the actual design rationale the agent needs. Can be multiple paragraphs for complex stories.
- **File Domain**: Files this story exclusively owns, with a note on what changes. No overlap between stories.
- **Interface Contracts**: Shared boundaries with other stories. Format: `file:symbol — shared with story-NNN, constraint`. Advisory, not enforced.
- **Acceptance Criteria**: 3-5 testable conditions. At least one E2E prefixed with "E2E:".

Include deferred stories from the previous sprint, renumbered to fit.

### Step 4: Sprint Goal

Write a one-sentence sprint goal. This becomes the sprint title.

### Step 5: Customer Confirmation

Present a **compact summary table** via `AskUserQuestion`:

- Sprint goal + milestone reference
- Story count and size distribution
- Table: ID, Title, Size, Deps

Options: "Confirm this sprint" or "Adjust sprint scope"

Do not write files until the customer confirms.

### Step 6: Write sprint.md

After confirmation, assemble in the enhanced format:

```bash
cat <<'SPRINTEOF' | python3 ${CLAUDE_SKILL_DIR}/scripts/save_sprint.py --smm-dir <SMM_DIR>
# Sprint: <sprint goal>

- **Sprint ID:** <NEXT_SPRINT_ID>
- **Started:** <today's date YYYY-MM-DD>
- **Milestone:** Milestone N: <name>

## System Context

See: system_context.md

## Stories

### story-001: <title>
- **Size:** <S|M|L>
- **Status:** ready
- **Dependencies:** <story-NNN or none>
- **Milestone:** execution_plan.md §Milestone N
- **Design Sources:** <doc> §section, <doc> §section

**Context:**
<Inlined design context from milestone details + codebase dive.
Multiple paragraphs for complex stories.>

**File Domain:**
- `path/to/file.py` — <what to change>
- `tests/test_file.py` — <tests to write>

**Interface Contracts:**
- `path/to/shared.py:function_name` — shared with story-002, constraint

**Acceptance Criteria:**
- <criterion 1>
- <criterion 2>
- E2E: <end-to-end test scenario>

### story-002: <title>
...
SPRINTEOF
```

All stories start with **Status: ready**. After writing, **output the full sprint.md content** for review.

### Step 7: Record Sprint Event

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "sprint" \
  --agent "xp-sprint-start" \
  --content "<sprint goal>" \
  --metadata '{"sprint_id": "<NEXT_SPRINT_ID>", "action": "start", "stories_planned": <count>}'
```

Then record a status event:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" \
  --agent "xp-sprint-start" \
  --content "Sprint <NEXT_SPRINT_ID> created: <N> stories (<size distribution>)" \
  --working-on '["sprint.md"]'
```

---

## Guidelines

- Every story needs at least one E2E acceptance criterion
- No XL stories — split during decomposition
- Stories ordered by priority (first = highest)
- No circular dependencies
- File domains must not overlap between stories — this enables parallel execution
- Interface contracts are advisory — they document shared boundaries, not enforce them
- Context should be specific enough for a subagent to plan and implement without reading the full milestone
- Keep acceptance criteria testable — no vague conditions
- Recommend 5-10 stories per sprint unless mostly S-sized
- The sprint should be achievable in scope
