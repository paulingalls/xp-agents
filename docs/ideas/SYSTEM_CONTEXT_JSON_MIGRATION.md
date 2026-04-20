# System Context — JSON Migration with Render CLI

## Problem

`system_context.md` is the one plan-artifact still stored as free-form markdown. The other three (`execution_plan.json`, `sprint.json`, `shared_mental_model.json`) are JSON-with-schema-with-render-CLI. This inconsistency has three costs:

1. **No schema enforcement.** Field budgets, required fields, type constraints can't apply. Drift is caught only at retro time (e.g., "skills count wrong, file inventory stale, module list missing new addition").
2. **Whole-file reads only.** Every consumer reads the full 25 KB. Skills that care about one section (e.g., `/xp-sprint-start` cares about stack + conventions) pay tokens for the whole doc.
3. **Agent-written inventory prose drifts.** Counts and module lists are written by `xp-system-analyzer` at session time; code evolves between sessions; drift accumulates.

Converting to JSON with a render CLI (mirroring `plan_cli.py` / `sprint_cli.py` / `smm_cli.py`) solves the first two directly and enables a fix for the third (runtime-derived fields).

## Related work

- **`docs/ideas/VERBOSITY_AUDIT.md` §5** — plan-surface audit identifying this as an opportunity and sizing it as its own initiative. That doc's per-field `maxLength` patterns for `execution_plan_schema.py` and `sprint_schema.py` should ship first; this migration reuses those patterns.
- **`plugins/xp-agents/smm/plan_cli.py`** — existing pattern to mirror (subcommands: `render`, `edit-milestone`, `update-status`, `exists`, `has-remaining`, `count`).
- **`plugins/xp-agents/smm/sprint_cli.py`** — existing pattern (subcommands: `update-story`, `add-story`, `list-stories`, `render`, existence checks).
- **`plugins/xp-agents/agents/xp-system-analyzer.md`** — the agent that writes `system_context.md` today; updates to emit JSON patches instead.
- **`plugins/xp-agents/skills/xp-system-context/`** — forked skill that invokes the analyzer; updates to invoke render for display.

## Proposed schema

The schema has a **generic core** (applies to any project using xp-agents) and a **project-specific extension point** for content unique to a given project.

### Generic core

```json
{
  "product": "<capped prose, ≤400 chars>",
  "architecture_overview": "<capped prose, ≤600 chars>",
  "stack": {
    "languages": ["..."],
    "runtime": "...",
    "dependencies_policy": "...",
    "package_manager": "..."
  },
  "modules": [
    {
      "name": "...",
      "purpose": "<≤200 chars>",
      "path": "relative/dir",
      "file_count": 0
    }
  ],
  "conventions": [
    "<each ≤150 chars>"
  ],
  "key_decisions": [
    {
      "topic": "...",
      "decision": "<≤200 chars>",
      "rationale": "<≤200 chars>",
      "source_event_id": "<12-hex>"
    }
  ],
  "sources": [
    "<pointer strings, e.g., 'CLAUDE.md', 'docs/ARCHITECTURE.md'>"
  ],
  "project_specific": [
    {
      "name": "<section name>",
      "content": "<any JSON: string, list, or object>"
    }
  ]
}
```

**Generic-core field budgets** (per-field `maxLength`, mirroring the event/pillar discipline from VERBOSITY_AUDIT.md):

| Field | Budget | Rationale |
|-------|--------|-----------|
| `product` | 400 | One-paragraph product pitch: what + why. |
| `architecture_overview` | 600 | High-level shape, key boundaries. Details in modules + project_specific. |
| `stack.*` | 100 each | Typed short answers. |
| `modules[].purpose` | 200 | Brief enough to scan the full module list quickly. |
| `conventions[]` | 150 | Strategic-binding only (echoes SMM Constraints filter from VERBOSITY_AUDIT §2). |
| `key_decisions[].decision` | 200 | The decision itself. |
| `key_decisions[].rationale` | 200 | Why, briefly. Full rationale in `source_event_id`. |

### Project-specific extension

`project_specific` is an ordered list. Each entry has a `name` (becomes section heading on render) and a `content` field that can hold any JSON — a string, a list, a nested object. Intentionally loose. The renderer dispatches on content type:

- **string** → renders as prose
- **list of strings** → renders as bullets
- **list of objects** → renders as a table if objects share keys, else as a repeated block
- **object** → renders as key/value pairs

**xp-agents project_specific examples:**
- `hook_api`: list of `{event, matcher, semantics, examples}` objects.
- `smm_engine`: object describing four-pillar model, event schema, CLI boundaries.
- `worktree_handling`: prose describing the teammate-spawn pattern.

**React webapp project_specific examples:**
- `component_library`: list of components with purposes.
- `state_management`: prose about Redux/Zustand conventions.
- `routing`: list of `{route, component, auth_required}` objects.

No schema constrains `project_specific` contents. The `name` field MUST be unique within the list.

## CLI surface

New module: `plugins/xp-agents/smm/system_context_cli.py`. Subcommands mirror `plan_cli.py`:

| Subcommand | Purpose |
|------------|---------|
| `render` | Emit the full markdown render. Default for backward-compatible reads. |
| `section <name>` | Render a single top-level field or project_specific entry as markdown. |
| `get <json-path>` | Emit raw JSON at a path (e.g., `modules[2].file_count`). |
| `edit-field <name>` | Accept JSON patch from stdin, merge into the named field. |
| `add-decision` | Append to `key_decisions` from stdin JSON. |
| `add-module` | Append to `modules` from stdin JSON. |
| `update-counts` | Runtime-derive `modules[].file_count`, `stack` details — see next section. |
| `validate` | Run schema validation, exit 1 on failure. |
| `exists` | Status check. |

`render` outputs markdown with canonical section order: Product, Architecture, Stack, Modules, Conventions, Key Decisions, Sources, then each `project_specific` entry in list order.

## Runtime-derived fields

Several fields currently drift because the writer is an agent working from session context, and the underlying counts change between sessions. The JSON migration is the moment to move these to runtime derivation:

| Field | Today | Proposed |
|-------|-------|----------|
| `modules[].file_count` | Agent-counted, drifts | Computed by `update-counts` at render time via directory scan |
| Skill / agent counts (if in project_specific) | Agent-counted, drifts | Same pattern: derived at render time |
| Test counts | Agent-counted, drifts | Same |

`update-counts` runs: (a) on explicit invocation; (b) as a pre-render hook in the `render` subcommand if `--fresh-counts` is passed; (c) potentially as a SessionStart hook if we want zero-drift read-time counts.

Explicit option: we keep these as written fields AND gate them behind validation that warns when the on-disk count diverges from reality. User-written freshness claim + programmatic audit.

## Migration

One-shot migration script: `plugins/xp-agents/smm/migrate_system_context.py`.

1. Parse current `system_context.md` by headings.
2. Map canonical headings to generic-core fields (Product → `product`; Architecture → `architecture_overview`; Stack → `stack`; Modules → `modules`; Conventions → `conventions`; Decisions → `key_decisions`).
3. Everything else becomes a `project_specific` entry named by its section heading.
4. Warn on un-mappable content that needs human review.
5. Write `system_context.json` alongside the existing `system_context.md`; keep the markdown for one release as the authoritative fallback; flip in the next release.

Agent / skill updates (ride with the migration sprint):

- **`xp-system-analyzer.md`** prompt: emit JSON patches via `system_context_cli edit-field <name>` / `add-decision` / etc., not whole-file markdown rewrites.
- **`xp-system-context/SKILL.md`**: invoke the analyzer with JSON-output instructions; then call `render` for user-visible display.
- **`xp-plan/SKILL.md`, `xp-sprint-start/SKILL.md`**, and any other skill currently doing `Read system_context.md`: switch to `system_context_cli render` (for full) or `system_context_cli section <name>` (for targeted).

## Downstream consumers

Concrete files likely to need updating:

- `plugins/xp-agents/skills/xp-system-context/scripts/preload.sh` — calls Read or similar today; switches to CLI.
- `plugins/xp-agents/skills/xp-plan/` — reads system_context for architecture context.
- `plugins/xp-agents/skills/xp-sprint-start/` — reads for stack + conventions.
- `plugins/xp-agents/agents/xp-system-analyzer.md` — output format change.
- `plugins/xp-agents/agents/xp-plan-reviewer.md` — if it reads system_context for drift checking.
- Tests referencing the markdown format.

## Implementation plan

Four stories, roughly M-sized total. Can run as one sprint OR parallel teammate fan-out if schema and CLI land in separate worktrees.

**Story 1: schema + validation.** Add `system_context_schema.py`, `maxLength` validation, unit tests. Mirror patterns from `execution_plan_schema.py` and `sprint_schema.py`.

**Story 2: CLI + renderer.** `system_context_cli.py` with all subcommands. Render handles generic core + project_specific dispatch. Unit tests on render output, edit-field patches, validate, section-name lookup.

**Story 3: migration.** `migrate_system_context.py` converts current markdown to JSON. One-shot script with integration test on both projects' actual `system_context.md`. Write `system_context.json` alongside existing `.md`; both projects keep both for one release.

**Story 4: agent + skill updates.** Update `xp-system-analyzer.md`, `xp-system-context` skill, `xp-plan`, `xp-sprint-start`, and any other reader. Tests that the skills still produce the same effective briefing content after the switch.

## Sequencing

Ship **after** VERBOSITY_AUDIT.md Phase 1 (schema enforcement for execution_plan / sprint / events). That sprint establishes the CLI-boundary-validation + `maxLength` patterns this migration reuses.

Ship **independently** of Phase 2 (SMM purpose audit), Phase 3 (compression), and Phase 4 (code changes) — this work is orthogonal.

Ship **before** the agent / skill prompt pass (VERBOSITY_AUDIT §8) if feasible — the system_context changes touch several of the same prompts, and bundling reduces churn.

## Non-goals

- **No new schema for `project_specific` contents.** Intentionally loose. Renderer type-dispatches; that's the only constraint.
- **No auto-generation of full system_context** from code. Agents still author the strategic content (product pitch, architecture narrative, key decisions). Only the drift-prone inventory fields (counts) become runtime-derived.
- **No markdown authoring.** The canonical store is JSON; markdown is a render. No one edits `system_context.md` directly after migration.
- **No multi-file split.** `system_context.json` stays one file — convenience of single-read is worth more than the modest size savings of per-section files.

## Success metrics

- `system_context.json` validates against schema on every write. Failing writes surface the over-budget field with trim suggestion.
- Skills that need one section read ~2–4 KB instead of 25 KB. Measure token spend before/after on a reference session.
- `xp-system-analyzer` invocations produce patches (not whole-file rewrites), catchable in retro as smaller event footprint.
- Zero "inventory drift" findings in retros for three consecutive sessions (runtime-derived counts).

## Open questions

- **Runtime-count fields — on-demand at render, or cached on a timer?** Per-render is simpler (no staleness); cached is faster but introduces a refresh question. Recommend per-render until measured to be slow.
- **Does `xp-system-analyzer` agent write directly to JSON, or does it continue to write narrative that a transform parses?** Direct JSON writes are cleaner; narrative-with-parse is more forgiving of agent drift. Recommend direct JSON writes with schema validation as the safety net.
- **Do `project_specific` entries need ordering guarantees beyond the list order?** Probably not — the writer chooses the order, and the renderer respects it. Flag if a specific agent needs re-ordering support later.
- **Does the renderer support multiple output formats (markdown, plain text, JSON pretty-print)?** Start with markdown only; add others if a consumer needs them.
