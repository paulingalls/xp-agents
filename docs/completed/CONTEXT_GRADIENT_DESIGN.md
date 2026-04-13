# Design: Replace Product Spec with Execution Plan Model

## Context

The current `product_spec.md` abstraction is too monolithic — it assumes greenfield product creation via an interview process in Claude Code. In practice:
- Most work is **change requests** against existing products (bugs, features, Jira issues)
- Product design belongs elsewhere (claude.ai, external docs, conversations)
- Even greenfield is really a sequence of incremental changes
- Sprint stories lack enough context for subagent parallel execution — they point at the spec but don't carry the design context a subagent needs

The goal: provide Claude Code with **necessary and sufficient context** to correctly execute changes, structured as a **context gradient** (broad system → impact zone → change zone).

## Design: The Context Gradient Model

### Layer 0: System Context (`system_context.md`, standalone)

A persistent, standalone document describing the product/system as a whole. **Separate from execution plans** because it describes the system, not any particular change. Created once, reused by every execution plan and sprint, auto-updated by sprint review when architecture changes are delivered.

```markdown
# System Context: <Product Name>

## Overview
<Thorough description of the product/system: what it is, who it's for,
how it works at a high level. Be as detailed as needed for complex
systems — correctness matters more than brevity.>

## Key Architecture
- <Component> — <role, language/framework, key responsibilities>
- <Component> — <role, interfaces it exposes>
- <How components connect — protocols, shared state, data flow>

## Technical Constraints
- <language/runtime requirements>
- <deployment constraints>
- <coding standards>
```

**Relationship to CLAUDE.md:**
- system_context.md is **complementary** to CLAUDE.md, not a replacement
- CLAUDE.md = "how to develop" (coding standards, build commands, conventions) — loaded automatically by Claude Code
- system_context.md = "what is this system" (product description, domain concepts, user-facing behavior)
- During creation, `/xp-plan` reads CLAUDE.md and references it where relevant (e.g., "For coding standards, see CLAUDE.md") rather than duplicating
- system_context.md fills gaps — product/domain context that CLAUDE.md typically doesn't cover
- system_context.md must be self-sufficient — it doesn't assume any particular CLAUDE.md format or content

**Lifecycle:**
- Created during the first `/xp-plan` invocation (or standalone via `/xp-system-context`)
- Referenced by execution plans and copied into sprints
- **Auto-updated by sprint review** when delivered milestones change the architecture (new components, changed interfaces, tech stack shifts)
- Rarely changes between sprints — most change requests don't alter the system architecture

### Layer 1: Execution Plan (`execution_plan.md`, replaces `product_spec.md`)

Created collaboratively — user brings sources, Claude reads them + does light codebase scan, together they produce:

```markdown
# Execution Plan: <title>

## Sources
| Label | Location | Type |
|-------|----------|------|
| Auth redesign | docs/auth-redesign.md | repo |
| PM conversation | (inline below) | pasted |

<details><summary>Source: PM conversation</summary>
<pasted content>
</details>

## Change Overview
<What's changing across all milestones. Current state → desired state.>

## Milestones

### Milestone 1: <name> [planned]
- **Goal:** <one sentence>
- **Definition of Done:** <testable condition>
- **Sources:** <label1> §section, <label2> §section (references into Sources table)

**Change Zones:**
- `src/auth/tokens.py` — <what changes>
- `src/auth/middleware.py` — <what changes>

**Impact Zones:**
- `src/api/routes.py` — <why: imports auth middleware>
- `tests/test_auth.py` — <why: tests the changed module>

**Design Details:**
- <implementation decisions, patterns to follow>

**Constraints:**
- <milestone-specific limits>
```

**Key rules:**
- Milestones are ordered (sequential execution, no explicit cross-deps needed)
- One sprint = one milestone (if too big, split the milestone)
- Status markers: `[planned]` → `[in-progress]` → `[delivered: sprint-NNN]`
- Delivered milestones stay as history, cannot be modified
- Flag milestones with >8 change zone files as "consider splitting"

### Layer 2: Enhanced Sprint (`sprint.md`)

Sprint planning takes the current milestone + does **deep codebase dive** to produce context-rich stories:

```markdown
# Sprint: <goal>
- **Sprint ID:** sprint-NNN
- **Started:** YYYY-MM-DD
- **Milestone:** Milestone N: <name>

## System Context
<Copied from system_context.md — shared by all stories>

## Stories

### story-001: <title>
- **Size:** S|M|L
- **Status:** ready
- **Dependencies:** none
- **Milestone:** execution_plan.md §Milestone N
- **Design Sources:** docs/auth-redesign.md §Token Refresh, Auth redesign §API Changes

**Context:**
<Design context for THIS story, inlined from milestone details +
codebase scan. Not a pointer — actual context the subagent needs.
Can be several paragraphs for complex stories.>

**File Domain:**
- `src/auth/tokens.py` — <what to change>
- `tests/test_tokens.py` — <tests to write>

**Interface Contracts:**
- `src/auth/middleware.py:validate_token` — shared with story-002, don't change signature

**Acceptance Criteria:**
- <criterion>
- E2E: <scenario>
```

**New per-story fields:**
- **Milestone** — which milestone in the execution plan this story belongs to
- **Design Sources** — direct references to original design docs (repo files, pasted sources) with section pointers. Preserves the connection to the full design work — a subagent can read these for deeper context.
- **Context** — inlined design context (the "deep zone"). Not just a pointer — actual design rationale, decisions, and implementation guidance the subagent needs. Can be substantial for complex stories.
- **File Domain** — exclusive file ownership for parallel execution
- **Interface Contracts** — shared boundaries between stories (advisory, not enforced)

### Layer 3: Story Execution (unchanged)

Subagents receive the full story + system context. Each story is now self-contained: the subagent understands the system (broad), the change area (medium via context + file domain), and its specific work (deep via acceptance criteria + file domain).

## Skill Flow Changes

### `/xp-system-context` (NEW, forked skill)
Single owner of `system_context.md`. Delegates to subagent for autonomous analysis:
1. **Read codebase** — scan project structure, key modules, architecture patterns
2. **Read CLAUDE.md** (if exists) — reference existing docs, avoid duplication
3. **Synthesize system context** — product overview, key architecture, technical constraints
4. **Write** `system_context.md` via atomic save script

No user interaction needed — pure analysis. User reviews output after and can re-invoke to update.

Invoked by: `/xp-plan` (if file missing), `/xp-sprint-review` (if architecture changed), or standalone.

### `/xp-plan` (replaces `/xp-product-spec`)
1. **System context check** — if `system_context.md` doesn't exist, invoke `/xp-system-context`
2. **Source gathering** — ask user for repo files, pasted content, or verbal description
3. **Light codebase scan** — read referenced files, glob for related files, map change/impact zones
4. **Milestone decomposition** — propose milestones from sources + scan, with change/impact zones and source references
5. **User confirmation** — present full plan, refine collaboratively
6. **Write** `execution_plan.md` via atomic save script

### `/xp-sprint-start` (enhanced)
1. **Milestone selection** — show `[planned]` milestones, user picks one
2. **Deep codebase dive** (NEW) — read all change zone + impact zone files, identify story boundaries, shared interfaces
3. **Story decomposition** (enhanced) — produce stories with Context, File Domain, Interface Contracts
4. **User confirmation** — compact summary table
5. **Write** `sprint.md` + mark milestone `[in-progress]` in execution plan

### `/xp-sprint-review` (adjusted)
- Marks milestones `[delivered: sprint-NNN]` instead of features
- Checks if delivered milestones changed the architecture — if so, invokes `/xp-system-context` to update

### Kickoff (adjusted)
- `NEEDS_EXECUTION_PLAN` replaces `NEEDS_PRODUCT_SPEC`
- References `/xp-plan` instead of `/xp-product-spec`

### Free mode — unchanged

## Files to Modify

**New:**
- `skills/xp-system-context/SKILL.md` — forked skill, owns system_context.md creation/updates
- `skills/xp-plan/SKILL.md` — new skill (replaces xp-product-spec)
- `scripts/save_execution_plan.py` — atomic write for execution_plan.md
- `scripts/save_system_context.py` — atomic write for system_context.md

**Modified:**
- `skills/xp-sprint-start/SKILL.md` — milestone selection + deep dive + enriched stories
- `skills/xp-sprint-review/SKILL.md` — milestone status instead of feature status
- `agents/xp-sprint-reviewer.md` — update to work with execution_plan.md
- `skills/xp-kickoff/SKILL.md` — reference /xp-plan
- `skills/xp-kickoff/scripts/check_session_needs.sh` — check execution_plan.md
- `smm/sprint_parser.py` — parse new sprint fields (Context, File Domain, Interface Contracts)
- `scripts/subagent_start.py` — include System Context when extracting stories for teammates
- `agents/xp-assign.md` — use pre-computed File Domains from stories
- `PROCESS_GUIDE.md` — update references
- `docs/ARCHITECTURE.md` — update to four-file architecture (events.jsonl + system_context.md + execution_plan.md + sprint.md)

**Migration:**
- Detect existing `product_spec.md` and offer to migrate (features → milestones)
- Old markers remain during transition period

## Verification

1. Create a test execution plan via `/xp-plan` with a real change request
2. Run `/xp-sprint-start` against a milestone — verify stories carry context gradient
3. Verify `sprint_parser.py` extracts new fields correctly
4. Run `/xp-assign` — verify it uses pre-computed file domains
5. Run full sprint cycle through review — verify milestone status updates
6. Test migration path from existing product_spec.md
