# Process Guide

## Practicing the Values

- **Communication**: Share *why*, not just *what*. Answer open questions promptly.
- **Simplicity**: Simplest thing that works. Deliver what was asked before adding extras.
- **Feedback**: Fix what `/xp-quality-review` flags. Tests are production code.
- **Courage**: Make the tough call. Use the better way; flag the old with a concern.
- **Honesty**: Record decisions, assumptions, and concerns in the SMM. Honor collective decisions; never silently override — record a concern or set `metadata.supersedes`.

## Sequential Discipline

The harness batches independent tool calls in parallel; XP flows are step-gated and sequential. Inside any xp skill, run one step per turn — make the call, observe, then decide the next. Batching a gated step with the next races unsettled state, and one failure cancels the whole batch.

- Never place an `AskUserQuestion` and the action that consumes its answer in the same block — the action runs against a guessed answer.
- Never spawn the same subagent more than once; duplicates collide on shared preload/marker state.
- Exemption: genuinely independent read-only calls (Glob, Grep, Read of unrelated files) may still batch — the rule targets dependent/gated calls only.

## Pillars

- **Intent** — what we're building. Cap 2-5.
- **Constraints** — architectural/process bounds. Implementation details belong in code comments. Cap 15-20.
- **Risks** — what could go wrong. Cap 2-5.
- **Wisdom** — durable lessons. Cap 5-10.

Read Intent and Risks at plan or sprint start; check Constraints when choosing an approach; apply Wisdom continuously.

## Resolution Discipline

Three link types close events and risk pillar items:
- **STRONG**: `metadata.resolves=[id]` (required when a decision answers a *non-blocking* question). Risk IDs shown as `[id]` in rendered SMM.
- **WEAK**: `references=[id]` on flag concerns — cascade-closes with the root.
- **STRUCTURAL**: `files=[...]` on reviewer concerns — commit-auto-link nudges for a `Resolves-Event:` trailer.

**A 🔴 question gates writes and clears ONLY via AskUserQuestion** (records the `answer`). A `decision`/`status` resolving the question id does NOT clear it and fabricates an answer never given.

## When to Run XP Skills

**Plan cycle:** `/xp-schedule` → `EnterPlanMode` → `ExitPlanMode` → `/xp-review-plan` → (teammate only) `/xp-assign` → execute. Multi-file changes (3+ files). State-derived gates: the schedule gate (pre-promotion window) blocks writes + plan-entry until `/xp-schedule` promotes; `.plan-awaiting-review` until reviewed; `.assign-pending` until assigned (teammate-mode plans only).

**Per commit (cadence set at kickoff):** *commit* — `/xp-quality-review` → `git commit`, gate blocks if skipped. *story* — gate defers; review at `/xp-story-close` Step 4.5b. At `/xp-{free,sprint,plan}-close`: threshold-gated `/code-review` (Step 4b, Workflow tool) + LLM `/security-review` (Step 4). Deterministic patterns scan staged diffs.

**Sprint flow:** `/xp-plan` → `/xp-sprint-start` → `/xp-schedule` → plan → `/xp-review-plan` → (teammate) `/xp-assign` → implement → `/xp-accept` → `/xp-sprint-review` → `/xp-sprint-close`. Story lifecycle: `ready` → `scheduled` → `in-progress` → `reviewing` → `closing` (Step 1.5 singleton lock) → `done`/`deferred`; AC-fail reverts to `in-progress`. `/xp-schedule` (kickoff tail + `/xp-accept` post-loop) solely owns promotion + `execution_mode`; `/xp-story-close` merges + cleans up only. Stop gate fires on in-motion stories.

**Session close:** `/xp-end-session` — emits `session_summary`, appends to `session_history.json`, populates next kickoff's `### LAST_SESSION` block + the `recent_summaries` of retro + housekeeper inputs.

**Multi-command AC:** `commands: list[str]` reports `commands[N] failed (exit RC): CMD`; single keeps `command failed`. Prefer `commands` over chained `&&` when mixing runners.

**File domain:** Declare `file_domain` per planner intent; over-declaring defeats cascade_size.

**Forked skills:** `/xp-review-plan`, `/xp-sprint-review`, `/xp-system-context` — preload + cleanup.

**Tests:** Check for FAIL/ERROR first. Never re-run the full suite to find failure names.

**Stop gates:** TDD gate — fix failing tests. Accept gate — run `/xp-accept` first. If a gate is wrong, record a `debt` event explaining why.

## State and CLIs

State lives in `SMM_DIR`: `shared_mental_model.json`, `sprint.json`, `execution_plan.json`, `system_context.json`, `session_history.json`. Resolve via `${CLAUDE_PLUGIN_ROOT}/smm/init.sh`.

CLIs (`sprint_cli.py`, `plan_cli.py`, `smm_cli.py`, `retro_cli.py`, `session_history_cli.py`, `append.sh`) accept `--smm-dir DIR`; run `--help` for subcommands. All event writes go through `${CLAUDE_PLUGIN_ROOT}/smm/append.sh` — never write `events.jsonl` directly. Content budgets enforced at write time.

### System Context

`system_context.json` (per-project, in `SMM_DIR`) holds stack, architecture, conventions, principles, branching stage, and acceptance surfaces. Read by session_start, `/xp-plan`, `/xp-sprint-start`, close-skill gates, and the plan/close reviewers. Create or refresh via `/xp-system-context`; patch via `system_context_cli.py` (`edit-{stack,branching}-field`; `add-*`/`edit-*`/`retire-*` for capped lists; `--help`). An empty `stack.test_command` disables the close-skill auto-merge gate.

**Principles vs conventions:** a principle, `reversed, makes this a different project`; a convention reversed only changes behavior. Principles soft cap 15 / hard cap 20; `retire-principle` before `add-principle` over soft.

### Event Types

| Type | Pillar | When to Use | Required Fields |
|------|--------|-------------|-----------------|
| `goal` | Intent | Project north star | content |
| `status` | (activity) | Current work | content, working_on |
| `concern` | Risks | Problem needing attention | content, severity, files (opt) |
| `question` | Risks | Need customer input | content, priority |
| `customer_input` | Intent | (Auto-logged) | content |
| `customer_intent` | Intent | Distilled request | content, intent_status |
| `decision` | Constraints | Architectural choice | content, topic |
| `convention` | Constraints | Team standard | content, topic |
| `assumption` | Risks | Stated belief | content |
| `discovery` | Risks | Unexpected finding | content |
| `debt` | Risks | Known tradeoff | content, files |
| `retrospective` | Wisdom | (Retro agent) | content |

### Question Priority

- **Blocking** — Both paths create significant rework. Desktop notification.
- **Assumed** (default) — State assumption and proceed.
- **Informational** — Nice to know.

### Other Fields

- **`working_on`** (status events) — JSON array of file paths being modified. Powers conflict detection.
- **`references`** — link related events by ID. Answers reference questions; discoveries reference contradicted assumptions.
- **Commit linking** — add `Resolves-Event: <12-hex-id>` trailer to commit body. Case-insensitive, comma-separated. Hook auto-populates `metadata.resolves`.

### Refactor Mode

Declare before behavior-preserving changes. TDD metric excludes file writes until next commit. Add a behavior test for any **new primitive** (module/function/class) — original-caller tests don't reach it.
