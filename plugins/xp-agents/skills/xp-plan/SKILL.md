---
name: xp-plan
description: >-
  Create or update execution_plan.json — collaborative planning that transforms
  external design sources into ordered development milestones with change zones,
  impact zones, and design details. Replaces /xp-product-spec for sprint-mode
  work. Use when starting a new change request or refining an existing plan.
effort: high
allowed-tools:
  - Read
  - Glob
  - Grep
  - AskUserQuestion
  - Skill
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(*/smm/plan_cli.py *)
  - Bash(python3 */scripts/branching.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Execution Plan

The preload above shows the current state: milestone counts + `EXECUTION_PLAN=<path>` (update mode), or "No execution plan found" (create mode). It also reports whether system_context.json exists.

## Mode Detection

- **Create mode** (preload says "No execution plan found"): Follow the Create flow below.
- **Update mode** (preload shows existing plan): Follow the Update flow below.

## System Context Check

If the preload shows `NEEDS_SYSTEM_CONTEXT=true`, invoke `/xp-system-context` first using the `Skill` tool. The system context provides the broad product description that every sprint story will reference. Wait for it to complete before proceeding.

If `SYSTEM_CONTEXT=<path>` is shown, system context already exists. Read it for reference but do not modify it.

## Create Flow

### Step 1: Source Gathering

Ask the user what they're building or changing. Use `AskUserQuestion`:

> "What are the sources for this change? Provide file paths, paste content, or describe verbally."

Options: "Repo files (I'll give paths)", "Paste content", "I'll describe it", "Multiple sources"

For each source:
- **Repo files**: Use `Read` to load them. Record in the Sources table.
- **Pasted content**: Record inline in a `<details>` block in the Sources table.
- **Verbal description**: Record as a pasted source labeled with the topic.
- Keep asking "Any more sources?" until done.

### Step 2: Light Codebase Scan

After gathering sources, scan the codebase to understand what exists:
- Use `Glob` to find files related to the change areas mentioned in sources.
- Use `Read` on 3-5 key files to understand current architecture and patterns.
- Identify which files will likely change (change zones) and which are affected indirectly (impact zones).

### Step 3: Milestone Decomposition

Based on sources + codebase scan, propose ordered milestones. Each milestone should be roughly one sprint's worth of work.

For each milestone:
- **Goal**: One sentence describing what's delivered. Budget: ≤200 chars.
- **Definition of Done**: A concrete, testable condition. Budget: ≤300 chars.
- **Sources**: References into the Sources table with section pointers.
- **Change Zones**: Files/modules that will be modified, with a brief note on what changes. Note budget: ≤150 chars each.
- **Impact Zones**: Files affected indirectly (imports, tests, dependents), with why. Note budget: ≤150 chars each.
- **Design Details**: Key decisions and patterns — link to design docs for full rationale. Budget: ≤500 chars.
- **Constraints**: Milestone-specific limits or requirements. Budget: ≤150 chars each.
- **Acceptance Execution** (optional): How `/xp-sprint-review` verifies the milestone is done. Only include when the project has an automated acceptance surface in `system_context.json`. Format: `{"type": "<harness>", "command": "<run command>"}`. Optional `setup` and `notes` fields.

Guidelines:
- Milestones are ordered — each builds on the previous.
- Flag milestones with >8 change zone files as "consider splitting".
- Every milestone gets `[planned]` status.
- Keep design details specific enough that sprint planning can decompose into stories.
- **Acceptance execution**: check `system_context.json` for `acceptance_surfaces` with `status: "covered"`. If a milestone's `done` condition is verifiable by a covered surface's harness, populate `acceptance_execution` with the type and command. Leave null when no harness matches or the milestone is purely structural (docs, config, refactor).

### Step 4: User Confirmation

Present the complete plan to the user. Show:
1. Sources table
2. Change overview
3. Each milestone with its details

Use `AskUserQuestion`: "Does this plan look right? Any milestones to adjust?"

Iterate until the user confirms.

### Step 5: Write execution_plan.json

Assemble the plan as JSON and write via the CLI:

```bash
cat <<'PLANEOF' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> create
{
  "title": "<title>",
  "sources": [
    {"label": "<name>", "location": "<path or inline>", "type": "<repo|url|pasted>", "content": null}
  ],
  "overview": "<current state to desired state>",
  "milestones": [
    {
      "number": 1,
      "name": "<name>",
      "status": "planned",
      "delivered_sprint": null,
      "goal": "<one sentence>",
      "done": "<testable condition>",
      "sources": "<label> §section, <label> §section",
      "change_zones": [{"path": "path/to/file", "note": "<what changes>"}],
      "impact_zones": [{"path": "path/to/file", "note": "<why affected>"}],
      "design_details": "<decisions, patterns, implementation notes>",
      "constraints": ["<limit or requirement>"],
      "acceptance_execution": null
    }
  ]
}
PLANEOF
```

After writing, render the plan as markdown and **output it as text** so the user can see it:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> render
```

### Step 5b: Plan Branch Recommendation

A plan branch accumulates multiple sprints before merging to the primary branch — useful when intermediate milestones can't safely land on the primary one-by-one.

Skip this step when any of:
- Stage 0 (run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage` first).
- Single-milestone plan.
- Every milestone is independently shippable to the primary branch.

Otherwise, ask via `AskUserQuestion`: *"Create a plan branch so intermediate milestones don't land on the primary branch until the plan completes?"* — Yes / No.

On **Yes**, create the branch (the CLI records it into the plan):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  create-plan --cwd . --slug <plan-title-slug>
```

The CLI outputs `created: <branch>` for new branches or `resumed: <branch>` for pre-existing ones. If the output starts with `resumed:`, ask the user via `AskUserQuestion`: "Plan branch `<branch>` already exists. Adopt this branch for the new plan?" Options: "Adopt existing branch", "Choose a different slug". If the user chooses a different slug, re-run with the new slug.

On **No**, do nothing — sprints will base off the primary branch.

### Step 6: Record Event

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" \
  --agent "xp-plan" \
  --content "Created execution_plan.json with N milestones" \
  --working-on '["execution_plan.json"]'
```

## Update Flow

1. Read the full plan from `EXECUTION_PLAN=<path>` using `Read`.
2. Show the user a summary (milestone counts from preload, titles from file).
3. Ask what to change via `AskUserQuestion`: "Add milestones", "Refine existing", "Add sources", "Archive and start fresh", "Done".
4. For archive: run `python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> archive`, then switch to the **Create Flow** (step 1 above) so the user can start a new plan.
5. For new milestones, use the CLI to add:
   ```bash
   cat <<'EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> add-milestone
   {"number": N, "name": "...", "status": "planned", "delivered_sprint": null, ...}
   EOF
   ```
6. For new sources:
   ```bash
   cat <<'EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> add-source
   {"label": "...", "location": "...", "type": "repo", "content": null}
   EOF
   ```
7. For overview changes:
   ```bash
   echo "New overview text" | python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> set-overview
   ```
8. **NEVER modify `delivered` milestones** — only `/xp-sprint-review` does that.
9. Render and **output the plan as text** for review:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> render
   ```
10. Record a status event describing what changed.

## Guidelines

- Be collaborative — the user brings domain knowledge, you bring codebase knowledge.
- Scan the codebase before proposing milestones. Ground change zones in real files.
- Keep milestones focused. If a milestone has >8 change zone files, suggest splitting.
- Design details should be specific enough for sprint story decomposition.
- Sources are inputs to planning — once the plan is written, the plan should be self-contained. But milestones reference sources for traceability.
- Every new milestone gets `[planned]` status. No exceptions.
- The plan is a living document — start with what's known, refine as understanding grows.
