---
name: xp-plan
description: >-
  Create or update execution_plan.json: turn design sources into ordered
  milestones with change zones and design details.
effort: high
allowed-tools:
  - Read
  - Glob
  - Grep
  - AskUserQuestion
  - Skill
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/smm/plan_cli.py *)
  - Bash(python3 */scripts/branching.py *)
---

# Execution Plan

> **Sequential discipline.** Run Mode Detection → System-Context Check → Create
> (Steps 1–6) or Update (Steps 1–11) one step per turn — never batch an
> `AskUserQuestion` with the action consuming its answer (Step 1's source
> question vs writing the plan).

## Mode Detection

- **Create mode** (preload says "No execution plan found"): Follow the Create flow.
- **Update mode** (preload shows existing plan): Follow the Update flow.

## System Context Check

If the preload shows `NEEDS_SYSTEM_CONTEXT=true`, invoke `/xp-system-context` first via the `Skill` tool. Wait for it to complete.

If `SYSTEM_CONTEXT=<path>` is shown, read it for reference but do not modify it.

## Create Flow

### Step 1: Source Gathering (ALWAYS)

**Unconditional gate — do not skip.** Ask the user via `AskUserQuestion`:

> "What are the sources for this change? Provide file paths, paste content, or describe verbally."

Options: "Repo files (I'll give paths)", "Paste content", "I'll describe it", "Multiple sources"

For each source:
- **Repo files**: Use `Read` to load them. Record in the Sources table.
- **Pasted content**: Record inline in a `<details>` block in the Sources table.
- **Verbal description**: Record as a pasted source labeled with the topic.
- Keep asking "Any more sources?" until done.

### Step 2: Light Codebase Scan

- Use `Glob` to find files related to the change areas.
- Use `Read` on 3-5 key files to understand current architecture and patterns.
- Identify which files will likely change (change zones) and which are affected indirectly (impact zones).

### Step 3: Milestone Decomposition

From the sources + codebase scan, propose ordered milestones, each roughly one sprint's worth of work.

**Discovery pass for change_zones.** Before finalizing each milestone's `change_zones`: for every file you intend to declare, identify the symbols (functions, classes, top-level constants) it exports, then `Grep` for call-sites of those symbols. Union the call-site files into the milestone footprint — as `impact_zones` (read-only impact) or as additional `change_zones` (when the call-site itself must change). For symbols with too many call-sites to enumerate (>20 callers), record the count and a representative sample.

For each milestone:
- **Goal**: One sentence describing what's delivered. Budget: ≤200 chars.
- **Definition of Done**: A concrete, testable condition, behavior-shaped (Given/When/Then or equivalent — an observable outcome, not an implementation note). Budget: ≤300 chars.
- **Sources**: References into the Sources table with section pointers.
- **Discovery**: Run the pass above — its output feeds Change Zones and Impact Zones; never hand-roll those bullets without it.
- **Change Zones**: Files/modules modified, with a brief note. Union of declared paths and discovery call-sites that must change. Note budget: ≤150 chars each.
- **Impact Zones**: Files affected indirectly (imports, tests, dependents), with why. Remaining read-only call-sites land here. Note budget: ≤150 chars each.
- **Design Details**: Key decisions and patterns — link to design docs for full rationale. Budget: ≤800 chars.
- **Constraints**: Milestone-specific limits or requirements. Budget: ≤150 chars each.
- **Schedules** (optional): Ids of the recorded items (debt, concern) this milestone will FIX — `["<12-hex event id>", ...]`. The retrospective reads it to report "scheduled in M\<n\>" instead of escalating the item as aging debt. One test: **when this milestone ships, is the item resolved?** List the id only then — not when the milestone merely mentions it, touches its files, or rejects its *premise*. Judge the DEFECT, not the remedy the item proposed: fixing it a better way than prescribed still resolves it. Omit when the milestone answers nothing recorded.
- **Acceptance Execution** (optional): How `/xp-sprint-review` verifies the milestone is done. Only include when `system_context.json` has an `acceptance_surfaces` entry with `status: "covered"`. Format: `{"type": "<harness>", "command": "<run command>"}` for one command, or `{"type": "<harness>", "commands": ["<cmd1>", "<cmd2>", ...]}` for multiple (run in order, fail on first non-zero). Optional `setup` and `notes` fields. When a command is present, name the proof test file directly (the path-naming binary form, e.g. `npx playwright test <spec>`) rather than a bare script alias whose proof file is hidden in config.

Guidelines:
- Milestones are ordered — each builds on the previous.
- Flag milestones with >8 change zone files as "consider splitting".
- Every milestone gets `[planned]` status.
- Keep design details specific enough that sprint planning can decompose into stories.

### Step 4: User Confirmation

Present the complete plan: Sources table, change overview, each milestone with details.

Ask via `AskUserQuestion`: "Does this plan look right? Any milestones to adjust?"

Iterate until the user confirms.

### Step 5: Write execution_plan.json

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
      "schedules": ["<12-hex id of a recorded item this milestone fixes>"],
      "acceptance_execution": null
    }
  ]
}
PLANEOF
```

Then render the plan and **output it as text** for the user:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> render
```

### Step 5b: Plan Branch Recommendation

Skip when any of:
- Stage 0 (run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage`).
- Single-milestone plan.
- Every milestone is independently shippable to the primary branch.

Otherwise, ask via `AskUserQuestion`: *"Create a plan branch so intermediate milestones don't land on the primary branch until the plan completes?"* — Yes / No.

On **Yes**:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  create-plan --cwd . --slug <plan-title-slug>
```

The CLI outputs `created: <branch>` or `resumed: <branch>`. If `resumed:`, ask via `AskUserQuestion`: "Plan branch `<branch>` already exists. Adopt this branch for the new plan?" Options: "Adopt existing branch", "Choose a different slug". On different slug, re-run.

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
3. Ask via `AskUserQuestion`: "Add milestones", "Refine existing", "Add sources", "Archive and start fresh", "Done".
4. For archive: run `python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> archive`, then switch to the **Create Flow** (step 1 above).
5. For new milestones — author the same field set as Create Step 3, `schedules` included:
   ```bash
   cat <<'EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> add-milestone
   {"number": N, "name": "...", "status": "planned", "delivered_sprint": null, ...}
   EOF
   ```
6. For refining an existing milestone, patch only the fields that change. This is how an item recorded *after* the plan was written gets scheduled — a patched key REPLACES its old value, so send `schedules` as the full new list:
   ```bash
   cat <<'EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> edit-milestone N
   {"schedules": ["<12-hex event id>"]}
   EOF
   ```
7. For new sources:
   ```bash
   cat <<'EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> add-source
   {"label": "...", "location": "...", "type": "repo", "content": null}
   EOF
   ```
8. For overview changes:
   ```bash
   echo "New overview text" | python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> set-overview
   ```
9. **Never patch `status` or `delivered_sprint`, and never touch a `delivered` milestone** — `/xp-sprint-review` owns delivery via `update-status`. `edit-milestone` refuses all three.
10. Render and **output the plan as text** for review:
    ```bash
    python3 ${CLAUDE_PLUGIN_ROOT}/smm/plan_cli.py --smm-dir <SMM_DIR> render
    ```
11. Record a status event describing what changed.
