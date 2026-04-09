# Process Guide

## Practicing the Values

How we execute XP values in this plugin:

**Honesty through the Shared Mental Model:**
Ground truth lives in the SMM. Record every architectural decision with topic and rationale. Never silently override — either record a concern before changing an existing decision, or set `metadata.supersedes: [<prior_decision_id>]` on the new decision to acknowledge the override explicitly. State assumptions explicitly when proceeding with uncertainty. Raise problems early: bad pattern → concern, need input → question, unexpected finding → discovery, tradeoff → debt. Trace work to customer needs — if you can't connect it to a goal, question whether it should be done.

**Communication through events:**
Decisions in your head don't exist for the team — record them. Share *why*, not just *what*. Answer open questions in the SMM promptly.

**Feedback through review cycles:**
When `/simplify` or `/xp-quality-review` flags something, fix it. Disagreements get recorded as `debt` with a specific reason. Address retrospective Fix items. Tests are production code — they go through the same review cycle. Never skip or abbreviate reviews for test-only changes.

**Collaboration discipline:**
Honor collective decisions — don't bypass conventions without recording a concern. Don't silently modify files others are working on. Deliver what was asked before adding what you think is needed.

## When to Run XP Skills

These are not optional. Hooks enforce some as safety nets, but follow the process proactively rather than waiting to be blocked.

**Before implementing multi-file changes:**
- Use `EnterPlanMode` for 3+ files. Run `/xp-review-plan` after exiting.

**Per commit (commit-gated review cycle):**
- `/simplify` → `/xp-quality-review` → `/xp-security-triage` → `git commit`
- The commit gate blocks if you skip a step. Non-code commits skip automatically.

**After exiting plan mode:**
- Run `/xp-review-plan` before writing any code.

**Sprint iteration flow:**
- `/xp-product-spec` → `/xp-sprint-start` → implement → `/xp-accept`
- When done: `/xp-sprint-review` → `/xp-run-sprint-retro`

**Forked skills (all XP agents):**
- All XP agents are invoked via their corresponding skill, never launched directly with the Agent tool. Skills provide preload data and cleanup hooks that direct launches skip.
- `/xp-review-plan`, `/xp-security-triage`, `/xp-run-retrospective`, `/xp-housekeeping`, `/xp-sprint-review`, `/xp-run-sprint-retro`, `/xp-spawn-team`

**Agent Teams:**
- `/xp-spawn-team` for plan analysis and team sizing.
- Teammates receive TEAMMATE_GUIDE.md — they focus on implementation.

**When a Stop hook blocks you:**
- TDD gate: fix failing tests. Accept gate: run `/xp-accept` first.
- If a gate is wrong, record a `debt` event explaining why.

## Project Files

Project state lives in `SMM_DIR`: `shared_mental_model.json` (curated briefing), `sprint.md` (current sprint stories), `product_spec.md` (product requirements). Resolve `SMM_DIR` by running `${CLAUDE_PLUGIN_ROOT}/smm/init.sh`.

## Recording Events

Use `append.sh` for all event writes. Never write directly to `events.jsonl`.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "TYPE" \
  --agent "$AGENT_ID" \
  --content "Description here" \
  --working-on '["file1.ts", "file2.ts"]'
```

### Event Types and Four Pillars

Events are materialized into four pillars in the SMM:

| Pillar | Event Types | Purpose |
|--------|-------------|---------|
| **Intent** | `goal`, `customer_input`, `customer_intent` | What we're building and why |
| **Constraints** | `decision`, `convention` | Architectural choices and standards |
| **Risks** | `concern`, `assumption`, `debt`, `question`, `discovery` | What could go wrong, unknowns |
| **Wisdom** | `retrospective` (Try items) | Lessons learned, experiments to run |

| Type | Pillar | When to Use | Required Fields |
|------|--------|-------------|-----------------|
| `goal` | Intent | Project north star, what we're building | content |
| `status` | (activity) | What you're working on right now | content (working_on defaults to []) |
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

### Question Priority

- **🔴 Blocking** (`priority: "blocking"`) — Both paths create significant rework. Triggers desktop notification. Use sparingly.
- **🟡 Assumed** (`priority: "assumed"`) — **Default.** State your assumption and proceed. Escalate to 🔴 only if wrong path costs days.
- **🟢 Informational** (`priority: "info"`) — Nice to know. Won't change approach.

### The `working_on` Field

Every `status` event should include `working_on` — a JSON array of file paths currently being modified. This powers conflict detection and session end summaries. Update when you switch files.

### The `references` Field

Link related events by ID: an `answer` references the `question` it answers, a `discovery` references the `assumption` it contradicts.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "answer" \
  --agent "main" \
  --content "Customer confirmed: use PostgreSQL" \
  --references '["question-id-here"]'
```

### Good vs Bad Events

**Good:** Specific, actionable, grounded — "Decided to use PostgreSQL for user data because SQLite can't handle concurrent writes" (decision). **Bad:** Vague or noisy — "Working on stuff" (status), "Something might be wrong" (concern).

### Common Recording Patterns

```bash
# Starting a new task
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "main" \
  --content "Starting auth module refactor to typed errors" \
  --working-on '["src/auth/handler.ts", "src/auth/middleware.ts"]'

# Making an architectural choice
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "main" \
  --content "Using typed error classes instead of string matching — safer refactoring" \
  --topic "error-handling"

# Flagging technical debt
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "debt" --agent "main" \
  --content "Legacy string error matching still in 3 edge cases — will migrate next pass" \
  --files '["src/auth/legacy.ts"]'

# Recording an assumption
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "assumption" --agent "main" \
  --content "Assuming all auth errors are subclasses of AuthError — not verified for third-party providers"
```

Read Intent and Risks before every significant action. Check Constraints when making architectural choices.
