---
name: smm-protocol
description: >-
  SMM event recording protocol. Use when recording decisions, questions,
  concerns, assumptions, discoveries, debt, or any project event.
effort: low
---

# SMM Event Recording Protocol

## Recording Events

Use `append.sh` for all event writes. Never write directly to `events.jsonl`.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "TYPE" \
  --agent "$AGENT_ID" \
  --content "Description here" \
  --working-on '["file1.ts", "file2.ts"]'
```

## Event Types and Four Pillars

Events are materialized into four pillars in the SMM. The mapping:

| Pillar | Event Types | Purpose |
|--------|-------------|---------|
| **Intent** | `goal`, `customer_input`, `customer_intent` | What we're building and why |
| **Constraints** | `decision`, `convention` | Architectural choices and standards |
| **Risks** | `concern`, `assumption`, `debt`, `question`, `discovery` | What could go wrong, unknowns |
| **Wisdom** | `retrospective` (Try items) | Lessons learned, experiments to run |

### All Event Types

| Type | Pillar | When to Use | Required Fields |
|------|--------|-------------|-----------------|
| `goal` | Intent | Project north star, what we're building | content |
| `status` | (activity) | What you're working on right now | content, working_on (file list) |
| `concern` | Risks | Problem needing attention | content, severity (low/medium/high) |
| `question` | Risks | Need customer input | content, priority |
| `customer_input` | Intent | (Auto-logged by hook) | content |
| `customer_intent` | Intent | Distilled customer request | content, intent_status (open/delivered/superseded) |
| `decision` | Constraints | Architectural choice made | content, topic |
| `convention` | Constraints | Team standard established | content, topic |
| `assumption` | Risks | Stated belief, may need verification | content |
| `discovery` | Risks | Unexpected finding | content |
| `debt` | Risks | Acknowledged tradeoff, known issue | content, files (affected file list) |
| `retrospective` | Wisdom | (Written by retrospective agent) | content |
| `session_end` | (lifecycle) | (Auto-logged by hook) | content |

## Question Priority Guide

- **🔴 Blocking** (`priority: "blocking"`) — Both paths create significant rework. Triggers desktop notification. Use sparingly.
- **🟡 Assumed** (`priority: "assumed"`) — **Default.** State your assumption and proceed. Escalate to 🔴 only if wrong path costs days.
- **🟢 Informational** (`priority: "info"`) — Nice to know. Won't change approach.

## The `working_on` Field

Every `status` event should include `working_on` — a JSON array of file paths currently being modified. This powers:
- Conflict detection (overlapping files between agents)
- Session end summaries

Update `working_on` when you switch files. The hooks auto-generate status events for Write/Edit, but you should record status for broader context changes.

## The `references` Field

Link related events by ID:
- An `answer` references the `question` it answers
- A `discovery` references the `assumption` it contradicts
- A `decision` references the `convention` it follows (or should reference)

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "answer" \
  --agent "main" \
  --content "Customer confirmed: use PostgreSQL" \
  --references '["question-id-here"]'
```

## Good vs. Bad Events

**Good events** are specific, actionable, and grounded:
- "Decided to use PostgreSQL for user data because SQLite can't handle concurrent writes from Agent Teams" (decision)
- "Auth middleware stores session tokens in cookies — legal flagged this for compliance review" (concern, severity: high)
- "Assuming the API rate limit is 1000 req/min based on docs, not tested" (assumption)

**Bad events** are vague or noisy:
- "Working on stuff" (status — what files? what goal?)
- "Something might be wrong" (concern — what? where? severity?)
- "Made some decisions" (decision — what decision? what topic?)

## Reading the Materialized View

The SMM is organized into four pillars:

- **Intent** — Goals, customer inputs, and customer intent. What we're building and why.
- **Constraints** — Decisions and conventions. The architectural guardrails.
- **Risks** — Concerns, assumptions, debt, questions, discoveries. What could go wrong.
- **Wisdom** — Retrospective Try items. Lessons learned from past sessions.

Read Intent and Risks before every significant action. Check Constraints when making architectural choices.

## Common Recording Patterns

### Starting a new task
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "main" \
  --content "Starting auth module refactor to typed errors" \
  --working-on '["src/auth/handler.ts", "src/auth/middleware.ts"]'
```

### Making an architectural choice
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "decision" \
  --agent "main" \
  --content "Using typed error classes instead of string matching for auth errors — safer refactoring, better IDE support" \
  --topic "error-handling"
```

### Flagging technical debt
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "debt" \
  --agent "main" \
  --content "Legacy string error matching still in place for 3 edge cases — will migrate in next pass" \
  --files '["src/auth/legacy.ts"]'
```

### Recording an assumption
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "assumption" \
  --agent "main" \
  --content "Assuming all auth errors are subclasses of AuthError — not verified for third-party providers"
```

If the assumption is later contradicted, record a `discovery` event referencing the assumption by ID.
