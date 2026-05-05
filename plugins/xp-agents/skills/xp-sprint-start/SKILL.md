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
- **File Domain**: Files this story exclusively owns, with a note on what changes. No overlap between stories. Always include corresponding test files alongside source files (e.g., if `scripts/foo.py` is in the domain, include `tests/hooks/test_foo.py` too). This prevents domain accuracy issues where stories touch test files outside their declared domain. For investigation, verification, or research stories with no expected code changes, use an empty list `[]` — this marks the story as code-free and prevents false pipeline-gap noise in retro metrics.
- **Interface Contracts**: Shared boundaries with other stories. Format: `file:symbol — shared with story-NNN, constraint`. Advisory, not enforced.
- **Acceptance Criteria**: 3-5 testable conditions in **Given/When/Then prose** (per `docs/completed/ACCEPTANCE_TESTING_DOCTRINE.md §BDD Prose as the Universal Acceptance Format`). Use `And`/`But` to extend any clause. At least one criterion is an end-to-end scenario; mark it with the canonical `"E2E:"` prefix (the doctrine's signal for cross-cutting acceptance). Examples:
  - `"Given a registered user with a valid session, When they click 'Export', Then a CSV download starts within 2 seconds"`
  - `"Given the install command fails, When the workflow returns, Then phase is 'install' And the prior manifest is restored"`
  - `"E2E: Given the customer approves the preview, When the skill drives the full pipeline, Then the project's test runner reports green"`

  **BDD runner recommendation**: if the project's `system_context.json` lists a BDD harness (Cucumber, behave, SpecFlow, etc.) under `acceptance_surfaces`, write the criteria as executable `.feature` Gherkin and point `acceptance_execution.type` at that runner. Otherwise prose Given/When/Then plus the project's native test runner is the default.
- **Acceptance Execution** (optional): How `/xp-accept` runs this story's acceptance test. Only include when the project has an automated acceptance surface (test runner, CLI, HTTP endpoint). Omit for stories without automated acceptance — `/xp-accept` defaults to manual walkthrough.
  - `type`: Runner name (e.g., `pytest`, `playwright`, `bash`, `bats`, `cargo`).
  - `command`: Exact invocation (single command). Exit code 0 = pass.
  - `commands`: List of invocations run in order, fail on first non-zero (xor with `command`). Use when one AC needs multiple distinct verifications (e.g., `pytest` + a separate `grep`); `verify_acceptance.py --story <id>` handles the iteration and names the failing command in stderr.
  - `setup` (optional): Prerequisite commands (e.g., `docker compose up -d`).
  - `notes` (optional): Anything the agent needs to know before running.

Include deferred stories from the previous sprint, renumbered to fit.

### Step 3b: Capstone Story Proposal

When a milestone has **composition surface** — multiple stories that interact and whose seams could break without integration testing — propose a **capstone story** as the final story in the sprint.

**When to propose:** The project's `system_context.json` has `acceptance_surfaces` with a harness, or the milestone has 3+ stories with interface contracts between them.

**Capstone story structure:**
- **Last story** in sprint ordering, depends on all other stories
- **Deliverable** is the cross-cutting acceptance test file (e.g., `tests/acceptance/milestone-03.spec.ts`)
- **Acceptance criteria** render the milestone's prose `done` field into Given/When/Then — making the milestone's done-state executable
- **File domain** owns the cross-cutting test file exclusively
- **Acceptance execution** points at that test file
- If `system_context.json` has a matching `acceptance_surfaces` entry, the capstone story's `acceptance_execution` should use that surface's harness and conventions

**The capstone is optional.** Present it in the confirmation table and let the customer decline for small milestones, refactors, or surfaces where feature-level testing is impractical.

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

After confirmation, assemble as JSON and write via the CLI. The example below shows GWT prose criteria — when the project uses a BDD harness (per Step 3's runner recommendation), substitute Gherkin `.feature`-style scenarios into each criterion string instead.

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
      "acceptance_criteria": [
        "Given <precondition>, When <trigger>, Then <observable outcome>",
        "Given <precondition>, When <trigger>, Then <outcome A> And <outcome B>",
        "E2E: Given <precondition>, When <user action sequence>, Then <observable outcome>"
      ]
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

`create-sprint` forks off the plan branch when `execution_plan.json` has `branch` set, otherwise off the primary branch. It records the created branch name into `sprint.json`'s `branch_name` field, which downstream lookups read directly.

The CLI outputs `created: <branch>` for new branches or `resumed: <branch>` for pre-existing ones. If the output starts with `resumed:`, ask the user via `AskUserQuestion`: "Sprint branch `<branch>` already exists. Adopt this branch for the new sprint, or start fresh?" Options: "Adopt existing branch", "Delete and recreate". If "Delete and recreate", delete the branch first, then re-run the create-sprint command.

After creating the sprint branch, check for plan-branch divergence from primary:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  check-divergence --cwd .
```

If the output JSON contains a `warning` field, the plan branch has fallen behind primary. Record a concern event with the warning text and the suggested merge command:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "xp-sprint-start" \
  --content "<warning text from JSON>" --severity "medium"
```

**Stage 0-1:** Skip sprint branch creation.

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
