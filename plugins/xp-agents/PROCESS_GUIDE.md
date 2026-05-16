# Process Guide

## Practicing the Values

- **Communication**: Share *why*, not just *what*. Answer open questions promptly.
- **Simplicity**: Simplest thing that works. Deliver what was asked before adding extras.
- **Feedback**: Fix what `/simplify` or `/xp-quality-review` flags. Tests are production code.
- **Courage**: Make the tough call. Use the better way; flag the old with a concern.
- **Honesty**: Record decisions, assumptions, concerns in the SMM. State assumptions explicitly. Honor collective decisions; never silently override — record a concern or set `metadata.supersedes`.

## Pillars

- **Intent** — what we're building. Cap 2-5.
- **Constraints** — architectural/process bounds. Implementation details belong in code comments. Cap 15-20.
- **Risks** — what could go wrong. Cap 2-5.
- **Wisdom** — durable lessons. Cap 5-10.

Read Intent and Risks at plan or sprint start; check Constraints when choosing an approach; apply Wisdom continuously.

## Resolution Discipline

Three link types close events and risk pillar items:
- **STRONG**: `metadata.resolves=[id]` (required when a decision answers a question). Risk IDs shown as `[id]` in rendered SMM.
- **WEAK**: `references=[id]` on flag concerns — cascade-closes with the root.
- **STRUCTURAL**: `files=[...]` on reviewer concerns — commit-auto-link nudges for a `Resolves-Event:` trailer.

## When to Run XP Skills

**Plan cycle:** `EnterPlanMode` → `ExitPlanMode` → `/xp-review-plan` → `/xp-assign` → execute. Use for multi-file changes (3+ files). Marker-gated: `.plan-awaiting-review` blocks writes until reviewed; `.assign-pending` blocks until assigned.

**Per commit:** `/simplify` → `/xp-quality-review` → `git commit`. Commit gate blocks if skipped. Deterministic patterns scan staged diffs; LLM `/security-review` fires at `/xp-{free,sprint,plan}-close` Step 4.

**Sprint flow:** `/xp-plan` → `/xp-sprint-start` → `/xp-assign` → implement → `/xp-accept` → `/xp-sprint-review` → `/xp-sprint-close`. Story lifecycle: `ready` → `scheduled` → `in-progress` (teammates self-promote) → `reviewing` → `closing` (Step 1.5 singleton lock) → `done`/`deferred`; AC-fail reverts to `in-progress`. Solo JITs; teammates eager-batch. Stop gate fires on in-motion stories.

**Session close:** `/xp-end-session` — emits `session_summary` event, appends to `session_history.json`, populates next kickoff's `### LAST_SESSION` block AND the `recent_summaries` field of retro + housekeeper inputs. The render annotates the most-recent entry `(stale — N sessions ended without /xp-end-session)` when intervening sessions ended without a summary.

**Multi-command AC:** `commands: list[str]` reports `commands[N] failed (exit RC): CMD`; single keeps `command failed`. Prefer `commands` over chained `&&` when mixing runners.

**File domain:** Declare `file_domain` per planner intent; over-declaring defeats cascade_size.

**Forked skills:** `/xp-review-plan`, `/xp-sprint-review`, `/xp-{sprint,plan,free,story}-close`, `/xp-system-context` — preload + cleanup.

**Tests:** Check for FAIL/ERROR first. Never re-run the full suite to find failure names.

**Stop gates:** TDD gate — fix failing tests. Accept gate — run `/xp-accept` first. If a gate is wrong, record a `debt` event explaining why.

## State and CLIs

State lives in `SMM_DIR`: `shared_mental_model.json`, `sprint.json`, `execution_plan.json`, `system_context.json`, `session_history.json`. Resolve via `${CLAUDE_PLUGIN_ROOT}/smm/init.sh`.

CLIs (`sprint_cli.py`, `plan_cli.py`, `smm_cli.py`, `retro_cli.py`, `session_history_cli.py`, `append.sh`) accept `--smm-dir DIR`; run `--help` for subcommands. All event writes go through `${CLAUDE_PLUGIN_ROOT}/smm/append.sh` — never write `events.jsonl` directly. Content budgets enforced at write time.

### System Context

`system_context.json` (per-project, in `SMM_DIR`) holds stack, architecture, conventions, principles, branching stage, and acceptance surfaces. Read by `scripts/session_start.py`, `/xp-plan`, `/xp-sprint-start`, close-skill auto-merge gates, and the `xp-plan-reviewer` and `xp-close-reviewer` agents. Create or refresh via `/xp-system-context`; patch individual fields via `system_context_cli.py edit-stack-field`, `edit-branching-field`, `add-module`, `add-convention`, `add-principle`, `add-project-specific`, `add-acceptance-surface` (`--help` for full list). An empty `stack.test_command` disables the close-skill auto-merge gate.

**Principles vs conventions:** a principle, `reversed, makes this a different project`; a convention reversed only changes behavior. Principles soft cap 15 / hard cap 20 — over soft, `retire-principle <topic>` before `add-principle`.

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

Declare before behavior-preserving changes. TDD metric excludes file writes until next commit. Existing tests cover preserved behavior. Add a behavior test for any **new primitive** (module/function/class) — original-caller tests don't reach it.
