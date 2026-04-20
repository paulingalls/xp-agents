# Inline Agent Migration: Kickoff-Path Skills

## Problem

Two related failures with forked skills on the kickoff path:

1. **Silent invocation failure.** Forked skills (`context: fork` + `agent:`) sometimes complete from the main agent's perspective without the subagent actually running. Observed with `xp-housekeeper` and `xp-retrospective`. The skill "returns" but no work was done.

2. **Invisible output failure.** Even when the forked skill succeeds, its result arrives as a tool result — not user-visible text. Kickoff instructions telling the main agent to "echo the retrospective verbatim" have been skipped in multiple consecutive sessions despite instruction strengthening (commit 72dff5d). Only text the main agent *produces in its response* reaches the user; tool results do not.

Both failures block effective retrospective review and SMM curation at session start.

## Scope

Narrow migration focused on the three forked skills kickoff invokes. Other forked skills are out of scope and keep their current mechanism.

| Path | Skill | Agent | Action |
|------|-------|-------|--------|
| kickoff-only | `/xp-run-retrospective` | `xp-retrospective` | **Delete skill.** Kickoff calls Agent tool directly. |
| kickoff-only | `/xp-housekeeping` | `xp-housekeeper` | **Delete skill.** Kickoff calls Agent tool directly. Receives work-selection context. |
| kickoff + standalone | `/xp-system-context` | `xp-system-context` → `xp-system-analyzer` | **Rename agent** (name-collision defense). Kickoff calls Agent tool directly. Forked skill unchanged — still supports standalone invocation (e.g., after sprint review). |

Out of scope: `/xp-review-plan`, `/xp-security-triage`, `/xp-sprint-review`. Not called from kickoff, no observed echo-gap, lower failure frequency. Migrate separately if warranted later.

## Current Architecture

### Forked Skill Pattern (invocation)

```
User/agent invokes Skill tool → /xp-housekeeping
  ├── !`preload.sh` runs (deterministic, generates data files + KEY=VALUE output)
  ├── context: fork spawns subagent with agent type from `agent:` field
  ├── Skill content becomes the subagent's task prompt
  ├── Subagent runs with agent definition as system prompt
  ├── SubagentStop fires on completion (marker consumption, event recording)
  └── Skill tool returns subagent's final response as a tool result
```

The tool result contains the rendered output but is NOT user-visible. The main agent must re-output it in its own response — instruction-only enforcement.

### Inline + Agent Tool Pattern (proven: `/xp-quality-review` → `xp-code-reviewer`)

```
User/agent invokes Skill tool → /xp-quality-review
  ├── !`preload.sh` runs (deterministic)
  ├── Skill content loads into main agent's context
  ├── PostToolUse:Skill fires (before agent work)
  ├── Main agent follows skill instructions:
  │     ├── Calls Agent tool → xp-code-reviewer
  │     ├── SubagentStart fires → subagent_start.py injects prepared data
  │     ├── Agent runs with injected context
  │     ├── SubagentStop fires → markers consumed, events recorded
  │     └── Agent tool returns result to main agent
  └── Main agent acts on result per skill instructions
```

## Target Architecture

### Kickoff invokes agents directly (no wrapper skill)

```
xp-kickoff step 1 (if RETRO_NEEDED):
  → Agent tool (subagent_type=xp-retrospective)
  → SubagentStart fires, injects retro input + Try items + SMM/sprint renders
  → Subagent runs, writes retrospectives/<ts>.json, returns minimal result (file path + signature)
  → Main agent runs `retro_cli render <path>` — stdout = rendered MD, also drops echo marker
  → Main agent's next response echoes the rendered MD verbatim
  → Echo-gate hook clears marker on signature detection, or blocks next tool/prompt

xp-kickoff step 3 (if NEEDS_SYSTEM_CONTEXT and sprint mode):
  → Agent tool (subagent_type=xp-system-analyzer)
  → SubagentStart fires, injects SMM + existing context path
  → Subagent runs, writes system_context.md
  → Returns summary (no echo marker — output is a file, not user-visible analysis)

xp-kickoff step 6 (ALWAYS):
  → Agent tool (subagent_type=xp-housekeeper)
  → SubagentStart fires, injects curation data + work-selection events from current session
  → Subagent runs, writes curated SMM
  → Main agent runs `smm_cli render` (extended to also drop echo marker)
  → Main agent's next response echoes rendered SMM + summary verbatim
  → Echo-gate hook clears marker on signature detection, or blocks
```

### SubagentStart injection handlers

`subagent_start.py` dispatch table gains three entries. Each handler calls importable data-prep functions (not subprocess).

| Agent | Injection | Notes |
|-------|-----------|-------|
| `xp-retrospective` | Retro input (recent events + stats), Try items, SMM + sprint renders | Hybrid: SMM render inline, large event payload as file-path reference |
| `xp-housekeeper` | Curation data, work-selection events from current session, SMM renders | Hybrid as above. Work-selection data is new — lets curator see what was just adopted/selected |
| `xp-system-analyzer` | SMM_DIR, existing system_context.md path | Small payload, inline |

### Name-collision defense: why rename `xp-system-context`

A forked skill's preload runs only via the Skill tool invocation path. If the main agent calls Agent tool directly with the skill's name, the skill is bypassed and the agent spawns without its preload data. The established convention (followed by all other agents) is that agent names must differ from skill names:

- `/xp-housekeeping` → `xp-housekeeper`
- `/xp-run-retrospective` → `xp-retrospective`
- `/xp-review-plan` → `xp-plan-reviewer`
- `/xp-security-triage` → `xp-security-reviewer`
- `/xp-sprint-review` → `xp-sprint-reviewer`
- `/xp-system-context` → **`xp-system-context`** ← the one exception to fix

Rename: agent `xp-system-context` → `xp-system-analyzer`. Skill name and `system_context.md` output file are unchanged. Skill's `agent:` field updates to point at the renamed agent.

SubagentStart injection partially mitigates the collision risk (preload data flows regardless of entry path) — but not every agent has a SubagentStart handler, and clarity in logs/tests still wins.

### Echo enforcement: marker + hook

The mechanism that forces rendered output to become user-visible.

1. **Render CLI produces output and drops a marker:**
   - `retro_cli render <path>` and `smm_cli render` both:
     - Write rendered MD to stdout
     - Drop `<SMM_DIR>/.pending-render-<kind>.marker` containing the signature line to look for (e.g., `# XP Retrospective — Keep / Fix / Try`, `# Shared Mental Model`)

2. **Main agent echoes** the rendered MD verbatim in its next response. The signature line appears in the assistant's text output.

3. **Echo-gate hook** (`scripts/pre_tool_echo_gate.py`) registered on:
   - `PreToolUse` with matcher `Agent|Write|Edit|MultiEdit|Bash|Skill` — immediate feedback on next tool use
   - (Historical: initial design also registered on `UserPromptSubmit`. Later removed — blocking a user's prompt penalizes the wrong actor; PreToolUse enforcement is sufficient.)

   Hook logic:
   - Scan `<SMM_DIR>/.pending-render-*.marker` files
   - For each marker, read signature content
   - Parse `transcript_path` (JSONL) for `type=assistant` text blocks after marker mtime
   - Signature present in any such block → delete marker, allow
   - Signature absent → block with reason `"Unechoed render: <kind>. Output the contents of <file> verbatim before proceeding."`

Self-healing: markers auto-clear on detection. SessionStart hook can sweep stale markers from prior sessions if needed.

### Data prep: subprocess scripts → importable functions

Current `!` preload scripts become importable Python modules:

- `plugins/xp-agents/skills/xp-housekeeping/scripts/prepare_curation.py` → function in `plugins/xp-agents/smm/curation.py`
- Retro input assembly (currently in skill preload) → function in existing engine module or new `smm/retro.py`

SubagentStart handlers import these directly — no subprocess, no `.curation-input.json` tempfile unless the handler chooses the "write tempfile, inject path" hybrid for large payloads.

### Work-selection context injection (housekeeper-specific)

When kickoff invokes housekeeper, the SubagentStart handler additionally gathers events from the current session that reflect user-driven work decisions:

- `decision` events with `topic LIKE 'retro-try-%'` — freshly adopted retro Tries
- `status` events with `metadata.disposition IN ('deferred', 'dropped')` — Try items not adopted
- `goal` events — session goals just set

These are formatted into a "Session Work Selection" block in the housekeeper's additionalContext. The curator uses this to:
- Promote adopted Tries to wisdom when appropriate
- Record deferred Tries as debt or risk
- Update Intent pillar with just-set session goals
- Avoid re-suggesting dropped candidates

## Migration Steps

Executed in TDD order. One sprint-sized change; can be split into 2-3 stories if needed.

1. **Rename agent `xp-system-context` → `xp-system-analyzer`.** Update agent file, skill's `agent:` field, all test references. Verify forked skill still works via `/xp-system-context`.

2. **Extract data-prep as importable functions.** `prepare_curation.py` → `smm/curation.py::prepare_curation_input()`. Retro input assembly similarly. Migrate existing tests to unit tests for the new functions.

3. **Add render CLIs with marker emission.**
   - Extend `smm_cli render` to drop echo marker
   - Add `retro_cli render <json-path>` that emits rendered MD and drops marker
   - Tests: marker file contents, atomicity, signature line correctness

4. **Build echo-gate hook.** `scripts/pre_tool_echo_gate.py` handling `PreToolUse` (initial design also covered `UserPromptSubmit`; removed in a later revision). Transcript parser restricted to `type=assistant` text blocks. Tests: signature found (marker cleared, allowed), signature missing (blocked with reason), multiple pending markers, stale marker cleanup.

5. **Add SubagentStart dispatch entries.** Handlers for `xp-retrospective`, `xp-housekeeper` (with work-selection gathering), `xp-system-analyzer`. Tests: injection content matches expected data, handler is a no-op for irrelevant subagent_types.

6. **Update kickoff SKILL.md.** Rewrite steps 1, 3, 6 to use Agent tool + render + echo. Explicit instructions: run Agent tool → run render bash → echo the stdout in next response. Name the marker's signature line in the instructions so the main agent can see the enforcement gate.

7. **Delete forked skills.** Remove `plugins/xp-agents/skills/xp-run-retrospective/` and `plugins/xp-agents/skills/xp-housekeeping/` directories. Remove related registrations. Search for stale references.

8. **End-to-end kickoff integration test.** Exercises retro + work-selection + housekeeping flow via Agent tool calls with echo-gate active.

## Assumption Events

Record before first commit of this migration (per Try #2 — assumption-gate for design-shape commits):

1. **Marker naming doesn't collide** with existing `<SMM_DIR>/.*` files. Greenfield prefix `.pending-render-` is unused.
2. **Transcript parser restricts signature matching to `type=assistant` text blocks**, not tool-result content. Signatures appearing only in tool results must NOT clear markers.
3. **SubagentStart dispatch fires for direct Agent tool invocations by agent name.** Observed with `xp-code-reviewer` in the quality-review flow. Assuming consistent across all agent-tool calls, not just skill-triggered ones.

## Tradeoffs

### Gains
- **Kickoff is the single sanctioned path** for retro and housekeeping — no ambiguous entry points
- **Echo enforcement is mechanically backed** by markers + hook, not only instruction (addresses third consecutive retro's invisible-output pattern)
- **Work-selection data enriches housekeeper decisions** — freshly adopted Tries get first-class consideration during curation
- **Agent tool invocation is explicit** — fewer silent-failure surfaces
- **SubagentStart dispatch centralizes data injection** across all three migrated agents

### Costs
- **Two slash commands retired** (`/xp-run-retrospective`, `/xp-housekeeping`) — no documented standalone use case, reversible by adding thin wrapper skill if need arises
- **Added complexity**: one new hook, one new CLI, three new SubagentStart handlers, data-prep refactor — roughly 4-6 new source files + matching tests
- **Still instruction-dependent for the echo step** — the marker hook catches misses but doesn't prevent them on the first pass
- **One forked-skill path remains** for `/xp-system-context` standalone — existing risk, not new

### Unchanged
- SubagentStop marker consumption and event recording
- Forked skill pattern for plan-reviewer, security-reviewer, sprint-reviewer
- `/xp-quality-review` inline pattern
- Process guide injection via PostToolUse:Skill
- Allowed-tools lists on agent definitions

## Files Affected

### New
- `plugins/xp-agents/scripts/pre_tool_echo_gate.py` — marker-based echo enforcement hook
- `plugins/xp-agents/smm/retro_cli.py` (or extension to existing retro tooling) — render + marker drop
- `plugins/xp-agents/smm/curation.py` (or similar home for importable curation prep)
- `tests/hooks/test_echo_gate.py`
- `tests/hooks/test_subagent_tiers.py` entries for the three new handlers
- `tests/integration/test_kickoff_flow.py` (or extension) — end-to-end kickoff with Agent tool

### Modified
- `plugins/xp-agents/agents/xp-system-context.md` → rename to `xp-system-analyzer.md`, update description
- `plugins/xp-agents/skills/xp-system-context/SKILL.md` — update `agent:` field
- `plugins/xp-agents/skills/xp-kickoff/SKILL.md` — rewrite steps 1, 3, 6
- `plugins/xp-agents/scripts/subagent_start.py` — add 3 dispatch entries + handlers
- `plugins/xp-agents/hooks/hooks.json` — register echo-gate hook on PreToolUse (UserPromptSubmit registration removed in later revision)
- `plugins/xp-agents/smm/smm_cli.py` — add marker drop to render command
- `docs/ARCHITECTURE.md` — update hook map, injection table, subagent lifecycle

### Deleted
- `plugins/xp-agents/skills/xp-run-retrospective/` (entire directory)
- `plugins/xp-agents/skills/xp-housekeeping/` (entire directory)
- Tests specific to deleted skills (migrate useful assertions into kickoff integration tests)

## Decisions

1. **Delete retro and housekeeping skills outright** rather than converting to inline wrappers. Kickoff is the only sanctioned call site; wrapper skills add overhead without user-visible benefit. Re-adding a thin inline wrapper is trivial if standalone need arises later.

2. **Rename `xp-system-context` agent to `xp-system-analyzer`** to match the established naming convention that prevents Skill/Agent name collision. SubagentStart injection partially mitigates this class of bug, but clarity still wins.

3. **Keep `/xp-system-context` forked skill** for standalone invocation (e.g., after sprint review). Narrow migration scope; don't touch what isn't broken.

4. **Echo enforcement: marker + PreToolUse.** Not Stop-gate. Rationale: Stop can fire far from kickoff in long sessions. Marker approach gives tight feedback on the very next tool use. (Initial design also covered UserPromptSubmit; later removed — penalizes user for agent's failure.)

5. **Work-selection events injected into housekeeper** via SubagentStart handler. Rationale: curator making decisions about wisdom/risk promotions benefits from knowing what was just adopted/selected.

6. **`!` preload elimination is scoped to the three migrated skills only.** Other forked skills keep their preloads. Full preload elimination remains a future option.

7. **Marker mechanism is generalized** but initially used only for retro and SMM renders. Future skills that produce user-visible text can drop markers with the same hook — no hook change needed.

## Out of Scope

- Migration of `/xp-review-plan`, `/xp-security-triage`, `/xp-sprint-review`
- PostToolUse:Agent matcher adoption (deferred — SubagentStop covers current needs)
- Full preload-elimination across all agents
- Generalizing the marker mechanism to non-kickoff render paths in this sprint
