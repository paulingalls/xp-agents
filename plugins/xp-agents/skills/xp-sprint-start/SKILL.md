---
name: xp-sprint-start
description: >-
  Create sprint.json from an execution plan milestone or product spec.
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
  - Bash(python3 */scripts/branching.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Sprint Planning

You are the sprint planner. Your job is to create `sprint.json` by decomposing a milestone from `execution_plan.json` into context-rich stories the team can deliver — including in parallel via subagents.

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
- **Dependencies**: Other story IDs, or "none".
- **Milestone**: `execution_plan.md §Milestone N` — traces back to the milestone.
- **Design Sources**: Direct references to the original design documents (from the milestone's Sources field) with section pointers. Preserves the connection to the full design work.

Then the enriched sections:

- **Context**: 2+ sentences of what THIS story uniquely does — mechanical specifics, file-count scope, AC summary. **Story context must NOT copy text from milestone design_details or constraints — reference the milestone by number only.** The context field describes WHAT this story uniquely does, not WHY the milestone exists. Open with: *"Milestone M-N does X (see execution_plan.json). This story handles..."* Budget: ≤600 chars.
- **File Domain**: Files this story exclusively owns, with a note on what changes. No overlap between stories. Always include corresponding test files alongside source files (e.g., if `scripts/foo.py` is in the domain, include `tests/hooks/test_foo.py` too). This prevents domain accuracy issues where stories touch test files outside their declared domain.
- **Interface Contracts**: Shared boundaries with other stories. Format: `file:symbol — shared with story-NNN, constraint`. Advisory, not enforced.
- **Acceptance Criteria**: 3-5 testable conditions. At least one E2E prefixed with "E2E:".

Include deferred stories from the previous sprint, renumbered to fit.

### Step 4: Sprint Goal

Write a one-sentence sprint goal. This becomes the sprint title.

### Step 5: Customer Confirmation

Present a **compact summary table** via `AskUserQuestion`:

- Sprint goal + milestone reference
- Story count
- Table: ID, Title, Deps

Options: "Confirm this sprint" or "Adjust sprint scope"

Do not write files until the customer confirms.

### Step 6: Write sprint.json

After confirmation, assemble as JSON and write via the CLI:

```bash
cat <<'SPRINTEOF' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> create
{
  "sprint_id": "<NEXT_SPRINT_ID>",
  "goal": "<sprint goal>",
  "started": "<today YYYY-MM-DD>",
  "milestone": "Milestone N: <name>",
  "stories": [
    {
      "id": "story-001",
      "title": "<title>",
      "status": "ready",
      "dependencies": [],
      "milestone_ref": "execution_plan.json §Milestone N",
      "design_sources": "<doc> §section",
      "context": "<inlined design context>",
      "file_domain": ["path/to/file.py — <what to change>"],
      "interface_contracts": ["path/to/shared.py:fn — shared with story-002"],
      "acceptance_criteria": ["<criterion 1>", "E2E: <scenario>"]
    }
  ]
}
SPRINTEOF
```

All stories start with `"status": "ready"`. After writing, render and **output as text** for review:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> render
```

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
  --content "Sprint <NEXT_SPRINT_ID> created: <N> stories" \
  --working-on '["sprint.json"]'
```

### Step 8: Create Sprint Branch (Stage 2+)

Read the branching stage:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage
```

If stage >= 2, create the sprint branch:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  create-sprint --cwd . --sprint <sprint_id> --slug <goal-slug>
```

**Stage 0-1:** Skip sprint branch creation.

### Step 9: Create Story Branches

If stage >= 1, get the base branch for story branches:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  get-base --cwd .
```

Checkout the base branch, then create each story branch:
```bash
git checkout <base-branch>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  create --cwd . --story <story-id> --slug <title-slug>
```

After creating all branches, checkout the base branch:
```bash
git checkout <base-branch>
```

**Stage 0 or missing:** Skip branch creation entirely.
**Resume:** If a branch already exists, the CLI checks out the existing branch instead of failing.

---

## Guidelines

- Every story needs at least one E2E acceptance criterion
- No XL stories — split during decomposition
- Stories ordered by priority (first = highest)
- No circular dependencies
- File domains must not overlap between stories — this enables parallel execution
- Interface contracts are advisory — they document shared boundaries, not enforce them
- Context must not restate milestone rationale — reference it. Each layer has a job: system_context=WHERE, milestone=WHY, story=WHAT uniquely, design doc=FULL RATIONALE
- Keep acceptance criteria testable — no vague conditions
- Recommend 5-10 stories per sprint
- The sprint should be achievable in scope
