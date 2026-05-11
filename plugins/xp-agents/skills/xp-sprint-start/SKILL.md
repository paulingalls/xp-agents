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

For the selected milestone's **Change Zones** and **Impact Zones**: `Read` each change-zone file (structure + interfaces), `Read` impact-zone files (dependencies), and `Glob`/`Grep` for related files not listed (tests, imports).

Identify natural story boundaries (cohesive file groups changeable independently), shared interfaces, and file domains (each story exclusively owns its files — no overlap).

### Step 3: Story Decomposition

For each story:

- **Unique ID**: `story-001`, `story-002`, etc.
- **Title**: Clear, milestone-aligned name.
- **Dependencies**: Other story IDs, or "none".
- **Milestone**: `execution_plan.md §Milestone N`.
- **Design Sources**: Direct refs to original design docs (from the milestone's Sources field) with section pointers.
- **Context**: 2+ sentences of what THIS story uniquely does. **Do NOT copy text from milestone design_details or constraints — reference the milestone by number only.** Open: *"Milestone M-N does X (see execution_plan.json). This story handles..."* Budget: ≤600 chars.
- **File Domain**: Files this story exclusively owns. No overlap between stories. Always include corresponding test files alongside source files. For investigation/research stories with no expected code changes, use `[]` to mark the story code-free and prevent false pipeline-gap noise.
- **Interface Contracts**: Shared boundaries. Format: `file:symbol — shared with story-NNN, constraint`. Advisory.
- **Acceptance Criteria**: 3-5 testable conditions in **Given/When/Then prose** (per `docs/completed/ACCEPTANCE_TESTING_DOCTRINE.md`). Use `And`/`But` to extend. At least one is end-to-end, marked with the canonical `"E2E:"` prefix. Examples:
  - `"Given a registered user with a valid session, When they click 'Export', Then a CSV download starts within 2 seconds"`
  - `"Given the install command fails, When the workflow returns, Then phase is 'install' And the prior manifest is restored"`
  - `"E2E: Given the customer approves the preview, When the skill drives the full pipeline, Then the project's test runner reports green"`

  **BDD runner recommendation**: if `system_context.json` lists a BDD harness (Cucumber, behave, SpecFlow, etc.) under `acceptance_surfaces`, write criteria as executable `.feature` Gherkin and point `acceptance_execution.type` at that runner.
- **Acceptance Execution** (optional): How `/xp-accept` runs the test.
  - `type`: Runner name (`pytest`, `playwright`, `bash`, `bats`, `cargo`).
  - `command`: Single invocation. Exit code 0 = pass.
  - `commands`: List run in order, fail on first non-zero (xor with `command`). Prefer `verify_acceptance.py --story <id>` for multi-command iteration + first-red stderr.
  - `setup` (optional): Prerequisites (e.g., `docker compose up -d`).
  - `notes` (optional): Anything the agent needs before running.

Include deferred stories from the previous sprint, renumbered.

### Step 3b: Capstone Story Proposal

When a milestone has **composition surface** (multiple interacting stories whose seams could break without integration testing), propose a **capstone story** as the final story.

**When to propose:** `system_context.json` has `acceptance_surfaces` with a harness, OR the milestone has 3+ stories with interface contracts.

**Structure:** last story, depends on all others; deliverable is the cross-cutting acceptance test file (e.g., `tests/acceptance/milestone-03.spec.ts`); acceptance criteria render the milestone's prose `done` into Given/When/Then; file domain owns the cross-cutting test; `acceptance_execution` points at that file (use the matching `acceptance_surfaces` harness when present).

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

After confirmation, assemble as JSON and write via the CLI (substitute Gherkin scenarios for the GWT prose if a BDD harness applies — see Step 3).

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

After writing, render and **output as text** for review:
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

Read the branching stage; if >= 2, create the sprint branch:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  create-sprint --cwd . --sprint <sprint_id> --slug <goal-slug>
```

CLI outputs `created: <branch>` (new) or `resumed: <branch>` (pre-existing). On `resumed:`, ask via `AskUserQuestion` ("Adopt existing branch" / "Delete and recreate"); on "Delete and recreate", delete then re-run.

Then check for plan-branch divergence from primary:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  check-divergence --cwd .
```

If the output JSON has a `warning` field, record a concern:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "xp-sprint-start" \
  --content "<warning text from JSON>" --severity "medium"
```

**Stage 0-1:** Skip sprint branch creation.

---

## Guidelines

- No XL stories — split during decomposition
- 5-10 stories per sprint, achievable in scope
- Stories ordered by priority (first = highest)
- No circular dependencies
- Keep acceptance criteria testable — no vague conditions
- Layer separation when authoring context: system_context=WHERE, milestone=WHY, story=WHAT uniquely, design doc=FULL RATIONALE
