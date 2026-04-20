---
name: xp-assign
description: >-
  Analyze plan steps, decide execution mode (solo vs CLI teammates),
  and either proceed solo or spawn teammates for parallel execution.
  Auto-run after planning completes.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(*/scripts/spawn_teammate.py *)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Work Assignment

Analyze the plan and decide how to execute: solo (sequential) or with CLI teammates (parallel).

## Pre-flight Checks

1. If `PLAN_FILE` was not provided — output: "No plan file found. Enter plan mode and create a plan first." Stop.
2. Read the plan file at `PLAN_FILE` path.
3. If `SPRINT_FILE` was provided, read it for story context (optional — for status tracking only).
4. Analyze the plan's steps/tasks for parallelization potential.

## Mode Selection

Evaluate the plan steps and choose a mode:

**Solo** (sequential execution by the lead) when ANY of these apply:
- Plan steps have sequential dependencies between them
- Plan steps target overlapping files
- The plan is small (3 or fewer steps)

**CLI teammates** (parallel execution) when ALL of these apply:
- 2+ independent step groups with no dependencies between them
- Steps target non-overlapping files
- Steps are substantial enough to justify coordination overhead

Present the recommendation to the user via `AskUserQuestion`:
- **Mode** (Solo or CLI Teammates) with rationale
- For teammate mode: which step groups run in parallel, which are sequential

## Solo Mode

If solo and a sprint is active with in-progress stories: write a `.story-assignment-main` marker so commit attribution works for the lead agent. Use the first in-progress story if only one, or the story most relevant to the plan scope:

```bash
python3 ${PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> list-stories --status in-progress
# Write the story ID to the assignment marker:
echo "story-NNN" > <SMM_DIR>/.story-assignment-main
```

Then output "Proceeding with solo execution." and stop.

## CLI Teammate Mode

For each parallel step group, write a prompt file and spawn a teammate:

### Step 1: Write the Prompt File

Write a self-contained prompt to a temp file. The teammate has no prior context:

```bash
Write({
  file_path: "/tmp/prompt-step-N.txt",
  content: "You are implementing step N: <title>

## Context
<inlined design context from the plan step>

## File Domain
<list of files this step exclusively owns>

## What to Change
<detailed changes from the plan step>

## Acceptance Criteria
<derived from the plan step's goals>

## Interface Contracts
<shared boundaries with other steps, if any>

## SMM Directory
SMM_DIR=<SMM_DIR from preload>

Follow strict TDD: write failing test, make it pass, refactor, commit.
Run the full review cycle before each commit: /simplify, /xp-quality-review, /xp-security-triage.

When done, report: what was implemented, which acceptance criteria are met,
commits made, and any concerns or assumptions that need attention."
})
```

If a sprint is active (SPRINT_FILE provided), include the relevant story ID in the prompt for status tracking, and pass `--story-id story-NNN` to spawn_teammate.py so commit events are attributed to the correct story for sizing metrics.

### Step 2: Spawn the Teammate

Launch each teammate via Bash with `run_in_background`:

```bash
Bash({
  command: "python3 ${PLUGIN_ROOT}/scripts/spawn_teammate.py --name teammate-step-N --smm-dir ${SMM_DIR} --prompt-file /tmp/prompt-step-N.txt --story-id story-NNN 2>&1 | python3 ${PLUGIN_ROOT}/scripts/teammate_output_filter.py --smm-dir ${SMM_DIR} --teammate-id teammate-step-N",
  run_in_background: true
})
```

The `--story-id` flag is optional — omit it when no sprint is active. When provided, spawn_teammate.py writes a `.story-assignment-{name}` file to the SMM directory so the commit hook can attribute commits to the correct story.

spawn_teammate.py creates a git worktree and launches `claude -p`. teammate_output_filter.py captures the result, writes a report file, and records cost/duration to the SMM.

Spawn all teammates in parallel (multiple Bash calls in one message, each with `run_in_background: true`).

### Post-Spawn Guidance

After spawning teammates, guide the lead:

1. **Wait** for Bash task notifications as each teammate completes
2. **Read** the task output for branch name, report file path, and cost
3. **Read** the report file for the teammate's summary
4. **Merge** each teammate's branch:
   ```
   git merge teammate-step-N --no-ff
   ```
5. **Resolve** any merge conflicts (file domains should prevent these)
6. **Run** the full test suite on the merged result
7. **Run** `/xp-accept` to verify acceptance criteria

## Recording Events

Record the mode decision:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "xp-assign" \
  --content "Execution mode: <Solo|CLI teammates> — <rationale>" \
  --topic "execution-mode"
```

For teammate mode, record an assumption per domain boundary:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "assumption" --agent "xp-assign" \
  --content "Domain boundary: <step-A files> independent of <step-B files>"
```
