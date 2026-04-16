# Inline Agent Migration: Forked Skills → Inline Skills + Agent Tool

## Problem

Forked skills (`context: fork` + `agent:` in SKILL.md) sometimes fail to spawn the subagent. The skill "completes" from the main agent's perspective without the agent actually running. This has been observed with both `xp-housekeeper` and `xp-retrospective`. The failure is silent — no error, no crash, the Skill tool just returns without the work being done.

## Proposed Solution

Replace forked skills with inline skills that explicitly call the Agent tool, following the pattern already proven by `/xp-quality-review` + `xp-code-reviewer`. Additionally, replace skill `!` preloads with SubagentStart hook handlers that inject prepared data via `additionalContext`.

### Two changes, one migration:

1. **Skill invocation**: Forked → inline + Agent tool
2. **Data preparation**: `!` preloads → SubagentStart handlers

## Current Architecture

### Forked Skill Pattern (6 skills)

```
User/agent invokes Skill tool → /xp-housekeeping
  ├── !`preload.sh` runs (deterministic, generates data files + KEY=VALUE output)
  ├── context: fork spawns subagent with agent type from `agent:` field
  ├── Skill content becomes the subagent's task prompt
  ├── Subagent runs with agent definition as system prompt
  ├── SubagentStop fires on completion (can consume markers, record events)
  └── Skill tool returns subagent's final response
```

PostToolUse:Skill fires after the Skill tool returns — i.e., after the subagent finishes.

### Inline + Agent Tool Pattern (1 skill: xp-quality-review)

```
User/agent invokes Skill tool → /xp-quality-review
  ├── !`preload.sh` runs (deterministic, generates data)
  ├── Skill content loads into main agent's context
  ├── PostToolUse:Skill fires (after content loads, BEFORE agent work)
  ├── Main agent follows skill instructions
  ├── Main agent calls Agent tool → xp-code-reviewer
  ├── SubagentStop fires when agent completes
  ├── Agent tool returns result to main agent
  └── Main agent acts on result per skill instructions
```

### Skills to Migrate

| Skill | Agent | Preload | Current |
|-------|-------|---------|---------|
| `/xp-housekeeping` | `xp-housekeeper` | `prepare_curation.py` → `.curation-input.json` | Forked |
| `/xp-run-retrospective` | `xp-retrospective` | retro input check + Try items | Forked |
| `/xp-review-plan` | `xp-plan-reviewer` | plan path + SMM + sprint render | Forked |
| `/xp-security-triage` | `xp-security-reviewer` | `mark_triaged.py` + diff | Forked |
| `/xp-sprint-review` | `xp-sprint-reviewer` | `prepare_review_data.py` | Forked |
| `/xp-system-context` | `xp-system-context` | SMM + system context path | Forked |

Already inline: `/xp-quality-review` (uses `xp-code-reviewer` via Agent tool).

## Target Architecture

### Inline Skill + Agent Tool + SubagentStart Injection

```
User/agent invokes Skill tool → /xp-housekeeping
  ├── !`preload.sh` runs (lightweight: SMM_DIR resolution + data prep only)
  ├── Skill content loads into main agent's context
  ├── PostToolUse:Skill fires (process guide injection, review nudges)
  ├── Main agent follows skill instructions:
  │     ├── Calls Agent tool → xp-housekeeper
  │     ├── SubagentStart fires → subagent_start.py injects prepared data
  │     ├── Agent runs with injected context
  │     ├── SubagentStop fires → markers consumed, events recorded
  │     └── Agent tool returns result (SMM + summary)
  └── Main agent displays result to user per skill instructions
```

### SubagentStart Injection Design

`subagent_start.py` already has a tiered dispatch table. Extend it with agent-specific data preparation handlers:

```python
_DISPATCH: dict[str, Callable[..., list[str]]] = {
    "Explore": _inject_explore,
    "xp-code-reviewer": _inject_full,
    "xp-agents:xp-code-reviewer": _inject_full,
    # New entries for migrated agents:
    "xp-housekeeper": _inject_housekeeper,
    "xp-agents:xp-housekeeper": _inject_housekeeper,
    "xp-retrospective": _inject_retrospective,
    "xp-agents:xp-retrospective": _inject_retrospective,
    "xp-plan-reviewer": _inject_plan_reviewer,
    "xp-agents:xp-plan-reviewer": _inject_plan_reviewer,
    # ... etc for each migrated agent
}
```

Each handler prepares the same data that the preload currently generates, but injects it as `additionalContext` instead of writing files.

### What Each Handler Needs

| Agent | Current Preload Data | SubagentStart Injection |
|-------|---------------------|------------------------|
| `xp-housekeeper` | `.curation-input.json` (curation data), SMM_DIR | Curation data as JSON in additionalContext, SMM_DIR path |
| `xp-retrospective` | `.retro-input.json` path, Try items, SMM/sprint renders | Retro input content, Try items text, SMM + sprint rendered |
| `xp-plan-reviewer` | Plan file path, SMM + sprint renders | Plan content (or path), SMM + sprint rendered |
| `xp-security-reviewer` | Security triage marker, diff stats | Diff stats, triage context |
| `xp-sprint-reviewer` | `.sprint-review-input.json`, plan path | Review data content, plan path |
| `xp-system-context` | SMM_DIR, system_context.md path | SMM_DIR, existing context path |

### Token Budget Considerations

Some preload data is large (curation input can be 2-5K tokens, retro input 1-3K). Options:

1. **Inject as additionalContext** — goes into conversation context. Fine for <5K tokens.
2. **Write to tempfile + inject path** — SubagentStart handler writes data to a tempfile and injects `Read this file: <path>` as context. Agent reads on demand. Better for large payloads.
3. **Hybrid** — small data inline, large data as file paths. The handler decides per agent.

Recommendation: **Hybrid.** SMM renders (~300-700 tokens) and paths go inline. Large structured data (curation input, retro input) stay as files with paths injected.

## Migration Strategy

### Phase 1: Housekeeping + Retrospective (highest value)

These are the two agents with observed forked-skill failures. Migrate first.

**Changes per agent:**

1. **SKILL.md**: Remove `context: fork` and `agent:` fields. Convert to inline skill that instructs the main agent to call the Agent tool with the correct subagent_type. Keep `!` preload for data file generation (still needed for file-based data).

2. **subagent_start.py**: Add dispatch entry. Handler reads the data file generated by the preload and injects relevant context as additionalContext.

3. **subagent_stop.py**: Keep marker consumption and event recording (already works). Remove any additionalContext return (already done for housekeeping in v2.13.3).

4. **Tests**: Update skill tests to verify inline invocation pattern. Add SubagentStart injection tests.

### Phase 2: Plan Reviewer + Security Reviewer

Lower urgency — less frequent, fewer observed failures.

### Phase 3: Sprint Reviewer + System Context

Lowest urgency. Migrate for consistency.

### Phase 4: Eliminate Preloads (optional)

Once all agents use SubagentStart injection, the preload scripts become redundant for data preparation. They'd only remain for SMM_DIR resolution and cleanup. Consider:

- Moving data prep entirely into SubagentStart handlers (Python, not shell)
- Keeping `!` preloads only for lightweight setup (SMM_DIR echo, cleanup)
- Or removing preloads entirely if SubagentStart handlers can resolve SMM_DIR independently (they can — `_common.get_validated_smm_dir()` already does this)

## Tradeoffs

### Gains
- **Reliability**: Agent tool invocation is explicit — the main agent controls spawning
- **Visibility**: Main agent sees the result directly as a tool result
- **Centralized data plumbing**: SubagentStart dispatch replaces scattered preload scripts
- **Consistent pattern**: All agents use the same invocation mechanism
- **Universal injection**: SubagentStart fires regardless of how the agent was spawned (Skill, Agent tool, teammate)

### Costs
- **PostToolUse:Skill timing**: Fires when skill loads (before agent work), not after agent completes. Any hook that depends on "skill work is done" needs to move to SubagentStop or PostToolUse:Agent.
- **Weaker execution guarantee**: Inline skills rely on the agent following instructions. Forked skills guarantee the subagent runs. Mitigated by the fact that the Agent tool call is explicit in the instructions.
- **Agent prompt construction**: The main agent builds the Agent tool prompt, so skill instructions must be clear about what to pass. Forked skills handle this automatically.
- **subagent_start.py growth**: Adding 6 handlers to the dispatch table. Mitigated by extracting handlers into a separate module if it gets large.

### Unchanged
- **SubagentStop**: Still fires, still handles markers and events. No change needed.
- **Allowed-tools**: Agent definitions already have `tools` fields. Inline skill `allowed-tools` covers the main agent's permissions for the Agent tool call itself.
- **Process guide injection**: Already moved to PostToolUse:Skill in v2.13.3. Works with both forked and inline timing (process guide is reference material, not dependent on agent output).

## Files Affected

### Per-Agent Migration (repeat for each agent)

| File | Change |
|------|--------|
| `skills/<skill>/SKILL.md` | Remove `context: fork`, `agent:`. Add Agent tool instructions. Remove `!` preload. |
| `skills/<skill>/scripts/preload.sh` | Delete (data prep moves to importable functions) |
| `skills/<skill>/scripts/*.py` | Refactor as importable functions (move to `smm/` or `scripts/`) |
| `scripts/subagent_start.py` | Add dispatch entry + handler that calls importable prep functions |
| `tests/hooks/test_subagent_tiers.py` | Add injection test for new dispatch entry |
| `tests/` | Move preload tests to unit tests for the importable functions |

### One-Time Changes

| File | Change |
|------|--------|
| `skills/_preload_base.sh` | Remove once all preloads are eliminated |
| `docs/ARCHITECTURE.md` | Update hook map, injection table, subagent lifecycle |
| `CLAUDE.md` | Update platform constraints if needed |

## Decisions

1. **Preloads are eliminated.** Data preparation scripts (`prepare_curation.py`, `prepare_review_data.py`, etc.) are refactored as importable Python functions callable from SubagentStart handlers. No subprocess calls from hooks — direct function imports. The existing test coverage migrates to unit tests for the importable functions.

2. **Main agent non-compliance is a non-issue.** If the inline skill's Agent tool call doesn't happen, the existing stop gates (housekeeping, TDD) catch it — same safety net as forked skill failures.

3. **PostToolUse:Agent is deferred.** Not needed for this migration. SubagentStop handles marker consumption and event recording. A PostToolUse:Agent matcher could replace some SubagentStop logic later but is out of scope.

4. **Skill `!` preloads may survive for lightweight SMM_DIR resolution** during the transition, but the target state is full elimination — SubagentStart handlers resolve SMM_DIR via `_common.get_validated_smm_dir()` which already works.
