---
name: xp-kickoff
description: >-
  Session start orchestrator: sequences retrospective, sprint setup, work
  selection, housekeeping. Use every session.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */smm/retro_cli.py *)
  - Bash(python3 */smm/smm_cli.py *)
  - Bash(python3 */scripts/branching.py *)
  - Bash(python3 */scripts/cadence_cli.py *)
  - Bash(python3 */scripts/teammate_config_cli.py *)
  - Read
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/check_session_needs.sh`

# Session Kickoff

> **Sequential discipline.** Run Step 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 strictly,
> one step per turn — make the call, observe, then decide the next. Never batch
> an `AskUserQuestion` with the action it gates (the Step 2 session-mode
> question vs the skill it launches); never spawn the same subagent twice.

**Complete ALL steps in order, Housekeeping (Step 6) included. Do NOT start working on the user's goal until every step is done.**

## Step 0: Prepare (ALWAYS)

**Bootstrap system context.** If the preload shows **NEEDS_SYSTEM_CONTEXT**, invoke `/xp-system-context` and wait. It sets the branching stage, so it MUST run before the stage gate below and before the mode fork.

**Read the branching stage.** Take `STAGE` from the preload's `### STAGE=N` marker — the default source, no Python call needed. Read it from Python instead when **no `### STAGE` marker is present** (fresh project before `/xp-system-context`; preload could not compute it), or to re-read after a path that mutated the stage since the preload ran (`/xp-system-context`, `/xp-stage-migration` below):
```bash
STAGE=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> stage)
```

If `STAGE < 2`, invoke `/xp-stage-migration` (it sets the Stage 2 floor directly, unless the user declines). Re-read `STAGE` after it returns.

**Orphan branch triage.** For each branch the preload lists under **ORPHAN_FREE_BRANCHES** or **ORPHAN_STORY_BRANCHES**, ask via `AskUserQuestion`: **merge / keep / delete?**
- **merge** — free branch: invoke `/xp-free-close` against it (check it out first if needed). Story branch: `branching.py merge-branch --cwd . --branch <name>`, then delete it.
- **keep** — leave the branch alone.
- **delete** — `branching.py delete --cwd . --branch <name>`. Do not auto-delete branches with commits ahead of their base.

## Step 1: Retrospective (ALWAYS)

Invoke the `xp-retrospective` agent via the Agent tool (`subagent_type=xp-agents:xp-retrospective`), passing `run_in_background:false` — the harness backgrounds Agent-tool subagents by default, and a backgrounded retrospective races the kickoff sequence and can bury its render before Step 2. Do NOT gate this step on the existence of `.retro-input.json`; the agent owns that branch, emitting a seed retrospective when the input is empty.

After it completes, render the latest retrospective:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/retro_cli.py --smm-dir <SMM_DIR> render
```

Output the render CLI's stdout to the user before continuing.

## Step 2: Session Mode (ALWAYS)

**Unconditional gate — do not skip.** Ask the user via AskUserQuestion: **"Free session or Sprint session?"**

- **Free session** — for brainstorming, Q&A, bug fixes, or any work that doesn't need sprint scaffolding.
- **Sprint session** — for planned work with execution plan, sprint stories, and acceptance criteria.

Record the session-mode goal event:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "goal" --agent "xp-kickoff" \
  --content "Free session" # or "Sprint session: <sprint-id>"
```

### Free session fork

Ask via AskUserQuestion: **"What's the focus for this session?"** The answer feeds both the branch slug and the session-focus goal event:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "goal" --agent "xp-kickoff" \
  --content "<user's session focus>"
```

If `STAGE >= 2`, create the free branch (slug = first 3-4 slugified words of the focus):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/branching.py --smm-dir <SMM_DIR> \
  create-free --cwd . --slug "<session-focus-slug>"
```

Tell the user which branch is in use. Then jump to Step 5.

### Sprint session fork

**Review cadence (opt-in).** Ask the user via AskUserQuestion: **"Review cadence: per-commit or per-story?"**

- **commit** (default) — `/xp-quality-review` runs before every commit (its xp-code-reviewer self-finds correctness).
- **story** — review relocates to `/xp-story-close` (the merge); intermediate commits proceed with a one-line deferral advisory. Nothing reaches the sprint base unreviewed.

Only when the user chooses **story**, write the cadence marker (the careful `commit` default needs no write — session-start already reset it):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cadence_cli.py --smm-dir <SMM_DIR> write story
```

**Teammate support (two-step opt-in).** Ask the user via AskUserQuestion: **"Teammate support for this session?"**

- **On** — teammates are enabled; proceed to Q2.
- **Off** — solo session; write token `off` and skip Q2:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_config_cli.py --smm-dir <SMM_DIR> write off
```

Q2 — Ask via AskUserQuestion: **"Default model for teammates?"**

Four options; `fable` rides the auto **"Other"** escape — on "Other", accept a valid token, else re-ask.

- **haiku** — mechanical tasks
- **sonnet** *(Recommended)* — pattern-following tasks
- **opus** — architecture tasks
- **inherit orchestrator** — same model as the lead

Write the chosen token:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/teammate_config_cli.py --smm-dir <SMM_DIR> write <token>
```

Then proceed to Step 3.

## Step 3: Execution Plan (sprint mode, conditional)

If the preload shows **NEEDS_EXECUTION_PLAN**, first `Read` the SMM file at `<SMM_DIR>/shared_mental_model.json` for context, then invoke `/xp-plan` and wait for it to complete. Otherwise skip to Step 4.

## Step 4: Sprint Start (sprint mode, conditional)

If the preload shows **NEEDS_SPRINT** and you haven't read the SMM in Step 3, `Read` `<SMM_DIR>/shared_mental_model.json` first. Then invoke `/xp-sprint-start` and wait for it to complete (it creates the sprint branch). Otherwise skip to Step 5.

## Step 5: Work Selection (ALWAYS)

Run `/xp-work-selection` and wait for it to complete. In free mode, stop after its Step 4 (skip sprint story selection).

## Step 6: Housekeeping (ALWAYS)

Invoke the `xp-housekeeper` agent via the Agent tool (`subagent_type=xp-agents:xp-housekeeper`) to curate the four-pillar SMM (Intent, Constraints, Risks, Wisdom). **Kickoff is not complete until housekeeping finishes.**

**Pass `run_in_background:false` — do NOT run housekeeping in the background.** The harness backgrounds Agent-tool subagents by default; without the flag the Stop gate admits a housekeeper that started minutes ago, then tells you to re-invoke — ending the turn is safe, but the flag is what actually finishes kickoff. Wait for the subagent before Step 7.

If the user said "skip" at any earlier step, still run housekeeping.

## Step 7: Render the curated SMM

After housekeeping completes, render:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py --smm-dir <SMM_DIR> render
```

Output the render CLI's stdout to the user, followed by the change summary the housekeeper agent returned (items added/removed/promoted/resolved, health warnings).

Kickoff is complete. **Do NOT stop.**

**If stories were selected in Step 5**, run `/xp-schedule` first — it promotes the next frontier (scheduled → in-progress), sets each story's execution_mode, and (solo) creates the branch. The schedule gate enforces this before planning. Then follow its handoff: enter plan mode, run `/xp-review-plan` after exiting, then (teammate mode only) run `/xp-assign`. If a story is already in-progress from a prior session, continue it directly into the plan cycle.

**If no sprint is active or the user chose free session**, begin working on the session goals.
