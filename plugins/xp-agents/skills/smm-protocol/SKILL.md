---
name: smm-protocol
description: >-
  SMM event recording protocol. Use when recording decisions, questions,
  concerns, assumptions, discoveries, debt, or any project event.
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

## Event Types

### Active Context Events (need attention)

| Type | When to Use | Required Fields |
|------|-------------|-----------------|
| `goal` | Project north star, what we're building | content |
| `status` | What you're working on right now | content, working_on (file list) |
| `concern` | Problem needing attention | content, severity (low/medium/high) |
| `question` | Need customer input | content, priority |
| `customer_input` | (Auto-logged by hook) | content |
| `customer_intent` | Distilled customer request | content, intent_status (open/delivered/superseded) |

### Reference Events (inform decisions)

| Type | When to Use | Required Fields |
|------|-------------|-----------------|
| `decision` | Architectural choice made | content, topic |
| `convention` | Team standard established | content, topic |
| `assumption` | Stated belief, may need verification | content |
| `discovery` | Unexpected finding | content |
| `debt` | Acknowledged tradeoff, known issue | content, files (affected file list) |
| `retrospective` | (Written by retrospective agent) | content |
| `session_end` | (Auto-logged by hook) | content |
| `security_review_requested` | (Auto-logged by push gate) | content |

## Question Priority Guide

- **🔴 Blocking** (`priority: "blocking"`) — Both paths create significant rework. Triggers desktop notification. Use sparingly.
- **🟡 Assumed** (`priority: "assumed"`) — **Default.** State your assumption and proceed. Escalate to 🔴 only if wrong path costs days.
- **🟢 Informational** (`priority: "info"`) — Nice to know. Won't change approach.

## The `working_on` Field

Every `status` event should include `working_on` — a JSON array of file paths currently being modified. This powers:
- Conflict detection (overlapping files between agents)
- Navigator context (what files are active)
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

The SMM has two tiers:

**Active Context** (top) — needs attention now:
- Project Goals, Conflict Alerts, Blocking Questions, Unacknowledged Concerns, Customer Intent, Agent Status

**Reference** (bottom) — informs decisions:
- Architecture Decisions, Conventions, Resolved Questions, Discoveries, Assumptions, Technical Debt, Resolved Concerns

Read Active Context before every significant action. Check Reference when making architectural choices.

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
