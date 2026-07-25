# xp-agents Development Guide

## What This Project Is

A Claude Code plugin that enforces XP practices via hooks. Broadcast event log (Shared Mental Model) replaces point-to-point mailboxes. All XP agents are implemented as hook handlers.

Read `docs/ARCHITECTURE.md` for design decisions, hook map, event types, and platform constraints.

## 🚨 Project-agnostic guardrail (load-bearing)

The plugin ships to projects in any language — Python, TypeScript/JavaScript, Rust, Go, Java, Ruby, anything. Sprint-103 leaked this assumption THREE times before being abandoned; see `docs/completed/XP_CODE_REVIEWER_MULTI_ANGLE_VERIFY.md` "What sprint-103 taught us" for the case study.

**Two layers of agnosticism, both required for any shipped agent/skill/script:**

1. **Vocabulary**: shipped prose (agent.md, SKILL.md, classifier prompts) must NOT use xp-agents-internal surface names (`ACCEPT_IN_FLIGHT`, `close_cycle_stop_gate`, `simplify_done`, `.assign-pending`, `review_cycle_done`, etc.) as if they were the rule. Use generic CS terms (state field, marker, gate, lifecycle pair, decision/exit point). This repo serves as a TEST FIXTURE for the plugin, not as its implementation vocabulary.

2. **Coverage**: shipped functionality must work on ANY language the user's projects use, not just the language the plugin is written in. **Language-specific implementation (regex, parser, language-tool integration) is a leak.** Acceptable: language-aware judgment (LLM subagents that read code in any language) or language-agnostic structural signals (works on bytes/lines, not on syntax). If you find yourself writing `if path.suffix != ".py":` in shipped plugin code, stop — that's the leak.

**Catch this at plan time, not at close time.** The plan-reviewer and close-reviewer are explicit downstream gates; the cheaper catch is at planning. When designing a new agent/skill that processes code, ask: "Does my approach work on TS, Rust, Go projects that ship NO Python?" If no, redesign before implementing.

System_context.json's `plugin-project-agnostic` principle is the formal pillar version of this; SMM convention `plugin-cross-language-coverage` reinforces it in the daily-rendered Constraints view.

## Scoping: CLAUDE.md vs PROCESS_GUIDE.md

CLAUDE.md is NOT shipped with the plugin — it's for plugin developers (us). PROCESS_GUIDE.md IS shipped and serves all plugin users. Dedup is one-directional: CLAUDE.md may lean on PROCESS_GUIDE.md, never the reverse.

## Official Claude Code Docs

Full docs index: https://code.claude.com/docs/llms.txt — always verify hook I/O formats against the hooks reference before implementing new hooks.

## Coding Standards

**Python 3.11+, stdlib only — for plugin code that ships** (`plugins/xp-agents/scripts/`, `smm/`, hooks, agents, skills). No external packages, no pip, no virtualenv at runtime; every shipped script must run with just `python3` on PATH. Tests under `plugins/xp-agents/tests/` are NOT bound by this constraint — they don't ship and can use external runners (e.g., `pytest`, `pytest-xdist`) if it speeds the suite without complicating local setup. Keep the test deps short and well-justified; the spirit is still "simple to run".

Use `match/case` for tool_name routing, event type handling, and hook input parsing. Use type hints. Use `pathlib` over `os.path`.

All scripts start with `#!/usr/bin/env python3`.

**`_required` narrowing convention.** For `T | None` loaders/lookups whose callers know the value MUST exist, add a sibling `<name>_required(...) -> T` helper that raises ValueError on None. Pyright narrows via the return type — no per-site `assert x is not None` crutch. See `sprint_store.load_sprint_required`, `execution_plan_store.load_plan_required`, `event_schema.get_required_budget`, and the `_AssertNotNoneMixin._assert_not_none` test helper. Reach for the existing pattern before hand-rolling a fourth.

**Keep files small and focused.** Target 500 lines max per file. Each module should have a single responsibility. When a file grows past 500 lines, look for a cohesive group of functions to extract into its own module (e.g., `coordination.py`, `security.py`, `concerns.py` were extracted from `_common.py`). Test files follow the same rule — split by the script or feature they test, not by milestone or chronology.

## Hook Patterns

See https://code.claude.com/docs/en/hooks.md for full reference. Minimum-viable shapes:

- **Input**: `input_data = json.load(sys.stdin)` — fields: `session_id`, `tool_name`, `tool_input`, `agent_id`
- **Context injection**: exit 0, stdout `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}`
- **Block (simple)**: `print("reason", file=sys.stderr); sys.exit(2)`
- **Block (JSON)**: exit 0, stdout `{"decision": "block", "reason": "..."}`
- **Prompt/agent hooks**: return `{"ok": true}` or `{"ok": false, "reason": "..."}` — NOT `decision`/`block`
- **Recursion prevention**: skip when `agent_type.startswith("xp-")` — every command hook gating an agent hook must check this

## SMM Path Resolution

All scripts resolve via `init.sh` (single canonical source). Honors `$SMM_DIR` env override. SMM lives at `${XP_AGENTS_DATA:-~/.xp-agents/data}/{project-id}/smm/` — user level, not project level, and deliberately NOT under `${CLAUDE_PLUGIN_DATA}`, which `claude plugin uninstall` deletes by default. A pre-existing SMM under a legacy plugin-data root is discovered there rather than abandoned. Never hardcode paths.

## Hook Registration

All paths use `${CLAUDE_PLUGIN_ROOT}` in `hooks/hooks.json`. Never relative paths — Claude Code copies plugins to a cache. See https://code.claude.com/docs/en/plugins-reference.md for format.

## Platform Constraints

- **Hook I/O matrix** — verify each hook's accepted output against the authoritative hooks reference (https://code.claude.com/docs/en/hooks.md) and the plugin-dev hook-development skill, not a hand-maintained copy.
- **`SubagentStop` `additionalContext` is delivered to the SUBAGENT and continues its turn** — it does NOT reach the parent/main agent. A hook that returns context on SubagentStop makes the subagent take another turn (which can bury its final message), so never use it to message the parent. To message the main agent after a subagent finishes, use a `PostToolUse:Skill|Agent` hook (e.g. `review_cycle_done.py`).
- **Stop hooks run in parallel** — a command hook's `additionalContext` is NOT visible to a prompt hook in the same entry.
- **Available events**: SessionStart, UserPromptSubmit, PreToolUse, PermissionRequest, PostToolUse, PostToolUseFailure, Notification, SubagentStart, SubagentStop, Stop, TeammateIdle, TaskCompleted, InstructionsLoaded, ConfigChange, WorktreeCreate, WorktreeRemove, PreCompact, PostCompact, Elicitation, ElicitationResult, SessionEnd.

## File Structure

Plugin at `plugins/xp-agents/`: manifest (`.claude-plugin/plugin.json`), guides (`XP_VALUES.md`, `PROCESS_GUIDE.md`, `TEAMMATE_GUIDE.md`), hooks (`hooks/hooks.json`), scripts (`scripts/`), agents (`agents/`), skills (`skills/`), SMM engine (`smm/`), tests (`tests/`).

## Error Handling

Fail loud, never corrupt, always recoverable: atomic writes (tempfile + rename), flock on `events.jsonl` with timeout fallback, schema validation at write time, graceful degradation when SMM is missing (exit 0).

## Event Appending

See PROCESS_GUIDE.md for event types, required fields, and common patterns.

## Testing

All tests run on every commit via lefthook. Leaky env vars (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_INDEX_FILE`, `SMM_DIR`, `XP_TEAMMATE_NAME`) stripped via `env -u` in lefthook.yml and at import time in `conftest.py`. The teammate var matters because the SessionStart hook reads it to choose the teammate guide; without stripping, integration tests assert against the wrong guide and every teammate's pre-commit fails.

**Setup** (one-time): `pipx install pytest && pipx inject pytest pytest-xdist`. See README "Development setup" for details.

```bash
# Run everything in parallel (~13s on 16 cores):
pytest -n auto
# Run a single file:
pytest plugins/xp-agents/tests/hooks/test_session_start.py
# Run a single test:
pytest plugins/xp-agents/tests/hooks/test_session_start.py::TestSessionStart::test_clear_source_returns_context
# Sequential fallback (no pytest installed):
python3 -m unittest discover -s plugins/xp-agents/tests -p "test_*.py" -v
```

Four suites: `tests/hooks/` (unit), `tests/integration/` (subprocess pipeline), `tests/engine/` (SMM engine), `tests/smm/` (foundation). Hook tests extend `_HookTestCase`, integration tests extend `_IntegrationTestCase`, engine tests extend `_SMMTestCase`, SMM tests extend `_TempRepoTestCase` — all from `tests/conftest.py`. Follow TDD: write the test first, watch it fail, then implement.

**Test isolation gotcha**: production code that depends on `os.environ` (e.g., `plugin_loader.resolve_plugin_root` reads `CLAUDE_PLUGIN_ROOT`) must NOT cache results — `@functools.lru_cache` on env-dependent loaders breaks isolation in source-order test runners (pytest), and the bug hides under unittest's alphabetical-by-class ordering. If you need memoization for a hot path, key the cache on the env var explicitly, or invalidate per-test.

## Key Decisions (Don't Revisit)

- Hooks-first — all XP agents are hook handlers
- SMM at `${XP_AGENTS_DATA:-~/.xp-agents/data}/{project-id}/smm/` (shared across worktrees; outside plugin-managed storage so no plugin lifecycle operation can delete it — reversed the original `${CLAUDE_PLUGIN_DATA}` decision, see CHANGELOG v4.20.0)
- Prompt nuggets deliver context at UserPromptSubmit, PostToolUse records to event log
- Quality reviewer is post-simplify skill (courage + drift + debt)
- Retrospective runs at session start, not session end
- Keep/Fix/Try framework with XP values as analytical lenses
- `customer_input` events from UserPromptSubmit
- Plan subagent output reviewed by SubagentStop hook
- Python 3.11+, stdlib only, zero dependencies
- Four-file architecture: events.jsonl + system_context.json + execution_plan.json + sprint.json (all JSON with schema validation and CLI; reversed three-file decision — product_spec was too monolithic for change-request workflows)
- Intent and Sprint are separate concerns — strategic/persistent vs tactical/ephemeral
- Interactive skills (sprint-start, plan) inline; review/analysis skills forked
- Teammates detected by `is_worktree_teammate()` — cwd-based detection via the `worktree-story-` path segment (location-independent; worktrees live out of the repo, a sibling of the SMM dir)
- No prep script for xp-assign — domain analysis is LLM judgment
- Commit-gated review cycle (not stop-gated) — enforced at commit time via PreToolUse:Bash
- CLI teammates over Agent Teams for sprint-driven parallel execution — each teammate is an independent `claude -p` process in a git worktree with full hook lifecycle, TDD + review cycle + commits

## Further Reading

- `README.md` — overview, install, how it works
- `docs/ARCHITECTURE.md` — hook map, event types, injection model, platform constraints
- `docs/SMM_DESIGN.md` — four-pillar Shared Mental Model design
- `docs/completed/CLI_TEAMMATE_DESIGN.md` — CLI teammate mechanism
