---
name: xp-sprint-start
description: >-
  Create sprint.json from an execution plan milestone: decompose it into
  context-rich stories with file domains and interface contracts.
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
  - Bash(python3 */scripts/surface_coverage.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Sprint Planning

> **Sequential discipline.** Run Steps 1 → 1b → 2 → 3 → 3b → 4 → 5 → 6 → 7 → 8
> one step per turn — never batch an `AskUserQuestion` with the action consuming
> its answer (the Step 5 scope confirmation vs the Step 6 sprint write).

You are the sprint planner: create `sprint.json` by decomposing a milestone from `execution_plan.json` into context-rich stories the team can deliver — including in parallel via subagents.

## Error Handling

If the preload output above shows **ERROR**, explain the problem to the user and stop.

## Deferred Story Carryover

If the preload shows **Deferred Stories from Previous Sprint**, these stories carry forward. Copy each `STORY:` id's `acceptance_criteria` and `file_domain` from the `SOURCE:` path it names — no CLI returns them once archived. Present them separately when confirming scope. A `WARNING:` line means the list is incomplete, not empty.

---

## Milestone-Based Planning (execution_plan.json)

Use this flow when `EXECUTION_PLAN=<path>` is shown in the preload.

### Step 1: Milestone Selection

Read the execution plan using `Read`. Show the user all `[planned]` milestones with their goals. Ask which milestone to include in this sprint using `AskUserQuestion`.

One sprint = one milestone. If a milestone has >8 change zone files, suggest splitting it before proceeding.

### Step 1b: Surface-Coverage Concerns

List the selected milestone's uncovered touched surfaces:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/surface_coverage.py --smm-dir <SMM_DIR> \
  uncovered --milestone <milestone-number>
```

For each surface name in the JSON array, emit one concern (medium):

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "xp-sprint-start" --severity "medium" \
  --content "Milestone <N> touches uncovered surface '<surface>' — no acceptance harness covers it"
```

### Step 2: Deep Codebase Dive

For the selected milestone's **Change Zones** and **Impact Zones**: `Read` each change-zone file (structure + interfaces), `Read` impact-zone files (dependencies), and `Glob`/`Grep` for related files not listed (tests, imports).

Identify natural story boundaries (cohesive file groups changeable independently), shared interfaces, and file domains (no two stories that could run *concurrently* may claim the same file).

### Step 3: Story Decomposition

For each story:

- **Unique ID**: `story-001`, `story-002`, etc.
- **Title**: Clear, milestone-aligned name.
- **Dependencies**: Other story IDs, or "none".
- **Milestone**: `execution_plan.json §Milestone N`.
- **Design Sources**: Direct refs to original design docs (from the milestone's Sources field) with section pointers.
- **Context**: 2+ sentences of what THIS story uniquely does. **Do NOT copy text from milestone design_details or constraints — reference the milestone by number only.** Open: *"Milestone M-N does X (see execution_plan.json). This story handles..."* Budget: ≤800 chars.
- **File Domain**: Files this story owns while it runs. Two stories may declare the same file only when they can never run at the same time — one transitively depends on the other. Stories with no dependency between them must have disjoint domains, or parallel teammates would step on each other; the sprint write refuses such a collision. A story building on an earlier story's file is normal: declare the dependency and share the path. A claim held by a done or deferred story never collides either — re-touching its file needs no dependency edge. Always include corresponding test files alongside source files. For investigation/research stories with no expected code changes, use `[]` to mark the story code-free and prevent false pipeline-gap noise.
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

  **Build `command` from `TEST_COMMAND`, never a hardcoded runner.** The preload emits `TEST_COMMAND=<declared command>`; start `command` from that value — only `TEST_COMMAND` knows which runner this project uses. Empty `TEST_COMMAND` means none declared: leave `acceptance_execution` unset, add a `notes` placeholder telling the customer to declare `stack.test_command` via `system_context_cli.py edit-stack-field`.

  **Scope and verify `command`/`commands`**: if `TEST_COMMAND` accepts a positional path (`pytest <path>`), append the story's test file so the command names that specific file — the path MUST live inside the story's `file_domain`, since the verify-touch gate matches it against the commits. If `TEST_COMMAND` runs the whole tree with no single-spec syntax (`cargo test`, `go test ./...`), use it unscoped — verifiable only if it structurally cannot omit the story's test file (it runs everything). Judge this from what `TEST_COMMAND` actually is, never a per-language table. Use the path-naming binary form (`npx playwright test <spec>`, `npx jest <path>`), not a bare script alias (`npm run test:e2e`, `pnpm test`) whose proof file is hidden in config and non-verifiable; prefer `verify_acceptance.py --story <id>` when in doubt.

Include deferred stories from the previous sprint, renumbered.

### Step 3b: Capstone Story Proposal

When a milestone has **composition surface** (multiple interacting stories whose seams could break without integration testing), propose a **capstone story** as the final story. Default opt-in — the customer may decline via `AskUserQuestion`.

**When to propose:** `system_context.json` has `acceptance_surfaces` with a harness, OR the milestone has 3+ stories with interface contracts.

**Build it** via the CLI (one behavior-shaped object AC per surface, `ready` status, depends on every sibling, acceptance_execution placeholder the implementer fills). Pass only the **covered** touched surfaces to `--surfaces` (the milestone's `surfaces_touched` minus the uncovered ones from Step 1b) — a capstone AC asserts the surface's suite runs and passes, which an uncovered surface has no harness for; those stay tracked by the Step 1b concern until scaffolded.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> build-capstone \
  --milestone "<milestone name>" --surfaces <covered-s1,covered-s2> \
  --depends-on <story-001,...> --story-id <story-NNN>
```

Pipe the printed JSON into `add-story`. Its ACs are **behavior-shaped** (Given/When/Then); the implementer fills the `acceptance_execution` placeholder with the real cross-cutting test invocation during the capstone's own story.

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

Assemble as JSON and write via the CLI (substitute Gherkin scenarios for the GWT prose if a BDD harness applies — see Step 3).

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
