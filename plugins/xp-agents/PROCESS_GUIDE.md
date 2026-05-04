# Process Guide

## Practicing the Values

- **Honesty**: Record decisions, assumptions, concerns in the SMM. Never silently override — record a concern or set `metadata.supersedes`. State assumptions explicitly.
- **Communication**: Share *why*, not just *what*. Answer open questions promptly.
- **Feedback**: Fix what `/simplify` or `/xp-quality-review` flags. Tests are production code — same review cycle.
- **Courage**: Make the tough call. If there is a better way than the existing, use the better way and flag the old with a concern.
- **Respect**: Honor collective decisions. Deliver what was asked before adding extras.


## Resolution Discipline

Three link types close events and risk pillar items:
- **STRONG**: `metadata.resolves=[id]` (required when a decision answers a question). Risk IDs shown as `[id]` in rendered SMM.
- **WEAK**: `references=[id]` on flag concerns — cascade-closes with the root.
- **STRUCTURAL**: `files=[...]` on reviewer concerns — commit-auto-link nudges for a `Resolves-Event:` trailer.

## When to Run XP Skills

Hooks enforce some as safety nets, but follow the process proactively.

**Plan cycle:** `EnterPlanMode` → `ExitPlanMode` → `/xp-review-plan` → `/xp-assign` → execute. Use for multi-file changes (3+ files). Marker-gated: `.plan-awaiting-review` blocks writes until reviewed, `.assign-pending` blocks until assigned.

**Per commit (review cycle):** `/simplify` → `/xp-quality-review` → `git commit`. Commit gate blocks if skipped. Deterministic patterns scan staged diffs; LLM `/security-review` fires at `/xp-{free,sprint,plan}-close` Step 4.5.

**Sprint flow:** `/xp-plan` → `/xp-sprint-start` → `/xp-assign` → implement → `/xp-accept` (loops `/xp-story-close`) → `/xp-sprint-review` → `/xp-sprint-close`. Story lifecycle: `ready` → `scheduled` (work-selection) → `in-progress` (xp-assign branch) → `reviewing` (xp-accept) → `done`/`deferred`; AC-fail reverts `reviewing → in-progress`. Solo JITs branches; teammates eager-batch all. Stop gate fires on `in-progress` only.

**File domain:** Declare `file_domain` per planner intent; over-declaring defeats cascade_size.

**Forked skills:** `/xp-review-plan`, `/xp-sprint-review`, `/xp-{sprint,plan,free,story}-close`, `/xp-system-context` — preload + cleanup.

**Tests:** Check for FAIL/ERROR first. Never re-run the full suite just to find failure names.

**Stop gates:** TDD gate: fix failing tests. Accept gate: run `/xp-accept` first. If a gate is wrong, record a `debt` event explaining why.

## Project Files

Project state lives in `SMM_DIR`: `shared_mental_model.json`, `sprint.json`, `execution_plan.json`, `system_context.json`. Resolve via `${CLAUDE_PLUGIN_ROOT}/smm/init.sh`.

## CLI Tools

CLIs (`sprint_cli.py`, `plan_cli.py`, `smm_cli.py`, `retro_cli.py`, `append.sh`) accept `--smm-dir DIR`; run `--help` for subcommands.

## Recording Events

Use `${CLAUDE_PLUGIN_ROOT}/smm/append.sh` for all event writes. Never write directly to `events.jsonl`. Content budgets enforced at write time — run `--help` for limits.

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

- **Blocking** (`priority: "blocking"`) — Both paths create significant rework. Desktop notification.
- **Assumed** (`priority: "assumed"`) — Default. State assumption and proceed.
- **Informational** (`priority: "info"`) — Nice to know.

### The `working_on` Field

Every `status` event should include `working_on` — JSON array of file paths being modified. Powers conflict detection.

### The `references` Field

Link related events by ID: `--references '["question-id"]'`. An answer references its question, a discovery references the assumption it contradicts.

### Linking Commits to Events

Add `Resolves-Event: <id>` trailer to commit body when a commit closes an SMM event or risk item. Case-insensitive, comma-separated. IDs are 12 hex chars. The hook auto-populates `metadata.resolves`.

### Common Patterns

```
append.sh --smm-dir DIR --type status --agent main --content "..." --working-on '[...]'
append.sh --smm-dir DIR --type decision --agent main --content "..." --topic "..."
append.sh --smm-dir DIR --type concern --agent main --content "..." --severity medium
```

### Refactor Mode

Declare before behavior-preserving changes. TDD metric excludes file writes until the next commit.

```
append.sh --smm-dir DIR --type assumption --agent main --content "refactor mode: <description>"
```

Existing tests cover preserved behavior. Add a behavior test for any **new primitive** the refactor extracts (module, function, class) — original-caller tests don't reach it.

Read Intent and Risks before every significant action. Check Constraints when making architectural choices.
