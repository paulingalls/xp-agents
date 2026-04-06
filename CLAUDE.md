# xp-agents Development Guide

## What This Project Is

A Claude Code plugin that enforces XP practices via hooks. Broadcast event log (Shared Mental Model) replaces point-to-point mailboxes. All XP agents are implemented as hook handlers.

Read `docs/ARCHITECTURE.md` for design decisions, hook map, event types, and platform constraints.

## Official Claude Code Docs (check for latest API)

- **Hooks reference**: https://code.claude.com/docs/en/hooks.md
- **Hooks guide**: https://code.claude.com/docs/en/hooks-guide.md
- **Plugins**: https://code.claude.com/docs/en/plugins.md
- **Plugins reference**: https://code.claude.com/docs/en/plugins-reference.md
- **Skills**: https://code.claude.com/docs/en/skills.md
- **Subagents**: https://code.claude.com/docs/en/sub-agents.md
- **Full docs index**: https://code.claude.com/docs/llms.txt

Always verify hook I/O formats against the hooks reference before implementing new hooks. The API evolves.

## Coding Standards

**Python 3.10+, stdlib only.** No external packages. No pip. No virtualenv. Every script must run with just `python3` on PATH.

Use `match/case` for tool_name routing, event type handling, and hook input parsing. Use type hints. Use `pathlib` over `os.path`.

All scripts start with `#!/usr/bin/env python3`.

**Keep files small and focused.** Target 500 lines max per file. Each module should have a single responsibility. When a file grows past 500 lines, look for a cohesive group of functions to extract into its own module (e.g., `coordination.py`, `security.py`, `concerns.py` were extracted from `_common.py`). Test files follow the same rule — split by the script or feature they test, not by milestone or chronology.

## XP Practices (Follow These)

**TDD.** Write the test first. Run it, watch it fail. Then write the implementation. No exceptions. If you're about to write a function, ask: where's the test?

**Small commits.** One logical change per commit. If you're thinking "and also" — that's two commits.

**Simple design.** Solve today's problem. Don't build abstractions for tomorrow's. If a function has more than one responsibility, split it.

**Refactor continuously.** After green, clean up. Rename unclear variables, extract repeated logic, remove dead code. Every commit should leave the code better than you found it.

**Courage.** If something is wrong, fix it now. Don't leave a TODO for later. If a design decision is proving wrong, say so — raise a concern.

## Hook Patterns

### Command Hook Input (stdin)
```python
import json, sys
input_data = json.load(sys.stdin)
session_id = input_data["session_id"]
tool_name = input_data.get("tool_name", "")
tool_input = input_data.get("tool_input", {})
agent_id = input_data.get("agent_id", "main")
```

### Command Hook Output — Context Injection (exit 0, stdout JSON)
```python
import json
output = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": "Your context string here"
    }
}
print(json.dumps(output))
sys.exit(0)
```

### Command Hook Output — Blocking (two patterns)

**Pattern 1: exit 2 + stderr** (simpler, used by our scripts)
```python
print("Explanation of why this is blocked", file=sys.stderr)
sys.exit(2)
```

**Pattern 2: JSON decision** (exit 0, for Stop/PostToolUse/SubagentStop/UserPromptSubmit)
```python
import json
output = {"decision": "block", "reason": "Explanation shown to Claude"}
print(json.dumps(output))
sys.exit(0)
```

### Prompt Hook Output (type: "prompt")
Prompt hooks return `ok`/`reason`, NOT `decision`/`block`:
```json
{"ok": true}
{"ok": false, "reason": "Must fix tests before stopping."}
```

### Agent Hook Output (type: "agent")
Same format as prompt hooks:
```json
{"ok": true}
{"ok": false, "reason": "Explanation of why action should be blocked."}
```

### Recursion Prevention
Every command hook that gates an agent hook must check:
```python
agent_type = input_data.get("agent_type", "")
if agent_type.startswith("xp-"):
    sys.exit(0)  # Skip — this is our own agent hook
```

## SMM Path Resolution

```python
import subprocess
git_common = subprocess.check_output(
    ["git", "rev-parse", "--git-common-dir"], text=True
).strip()
# Hash or sanitize git_common to create project-id
# SMM lives at: ${CLAUDE_PLUGIN_DATA}/{project-id}/smm/
```

All scripts resolve the SMM path this way. Never hardcode paths. Never use `.claude/smm/` — the SMM is at user level, not project level.

## Event Appending

Use `smm/append.sh` for all event writes. Never write directly to `events.jsonl`. ANSI escape codes are stripped from content automatically at write time.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "$AGENT_ID" \
  --content "Description here" \
  --working-on '["src/api/users.ts"]'
```

### Resolving Events

To resolve a goal, concern, or debt item, include `metadata.resolves`:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-housekeeping" \
  --content "Goal completed: description" \
  --working-on '[]' \
  --metadata '{"resolves": ["target-event-id"]}'
```

Resolution is the sole lifecycle mechanism — no aging, no pruning. Housekeeping curates the four-pillar SMM (Intent, Constraints, Risks, Wisdom) and omits resolved items.

## Hook Registration (hooks.json)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/pre_tool_write.py"
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/pre_tool_bash.py"
          }
        ]
      }
    ]
  }
}
```

All paths use `${CLAUDE_PLUGIN_ROOT}`. Never relative paths — Claude Code copies plugins to a cache.

## Platform Constraints

**PreToolUse `additionalContext` works** — confirmed, use it for all context injection to the agent.

**PostToolUse now supports `decision: "block"`** — top-level JSON field. Can also use `additionalContext`. We still prefer writing to event log for async feedback.

**PostToolUse agent hooks should be async** (`"async": true`) — feedback goes through event log anyway, no need to block.

**Stop hooks run in parallel** — all hooks in the same Stop entry fire concurrently. A command hook's `additionalContext` is NOT visible to a prompt hook in the same entry. Use exit 2 (or `decision: "block"`) for command hooks that need to block.

**Prompt/agent hooks use `ok`/`reason`** — NOT `decision`/`block`. Return `{"ok": false, "reason": "..."}` to block.

**Available hook events** (as of 2026-03-14): SessionStart, UserPromptSubmit, PreToolUse, PermissionRequest, PostToolUse, PostToolUseFailure, Notification, SubagentStart, SubagentStop, Stop, TeammateIdle, TaskCompleted, InstructionsLoaded, ConfigChange, WorktreeCreate, WorktreeRemove, PreCompact, PostCompact, Elicitation, ElicitationResult, SessionEnd.

## File Structure

```
plugins/xp-agents/
├── .claude-plugin/plugin.json         ← plugin manifest
├── XP_VALUES.md                       ← XP values (Honesty, Communication, Simplicity, Feedback, Courage, Respect)
├── PROCESS_GUIDE.md                   ← Process rules for lead/solo agents (skills, commit gates, sprint flow)
├── TEAMMATE_GUIDE.md                  ← DO/DON'T/SKIP/KEEP rules for Agent Team teammates
├── settings.json                      ← runtime config
├── hooks/hooks.json                   ← all hook registrations
├── scripts/*.py                       ← command hooks + shared modules
├── agents/*.md                        ← subagent definitions (6 agents: retrospective, plan-reviewer,
│                                        security-reviewer, sprint-reviewer, sprint-retro, spawn-team)
├── skills/                            ← forked + inline skills
│   ├── xp-kickoff/SKILL.md           ← session start orchestrator
│   ├── xp-run-retrospective/SKILL.md ← forked, delegates to xp-retrospective agent
│   ├── xp-question-triage/SKILL.md   ← inline, questions + retro Try items
│   ├── xp-goal-collection/SKILL.md   ← inline, session goals
│   ├── xp-housekeeping/SKILL.md      ← inline, four-pillar SMM curation
│   ├── xp-review-plan/SKILL.md       ← forked, delegates to xp-plan-reviewer agent
│   ├── xp-security-triage/SKILL.md   ← forked, delegates to xp-security-reviewer agent
│   ├── xp-quality-review/SKILL.md    ← inline, post-simplify courage + drift + debt
│   ├── xp-smm-protocol/SKILL.md      ← reference guide for event types
│   ├── xp-product-spec/SKILL.md      ← inline, product specification (product_spec.md)
│   ├── xp-sprint-start/SKILL.md      ← inline, sprint creation (sprint.md)
│   ├── xp-accept/SKILL.md            ← inline, acceptance testing gate
│   ├── xp-sprint-review/SKILL.md     ← forked, delegates to xp-sprint-reviewer agent
│   ├── xp-sprint-retro/SKILL.md      ← forked, delegates to xp-sprint-retro agent
│   └── xp-spawn-team/SKILL.md        ← forked, delegates to xp-spawn-team agent
└── smm/{init.sh,append.sh,_append_impl.py,event_schema.py,event_builder.py,
         resolution.py,materialize.py,read_delta.py,compact.py,seed_smm.py,
         sprint_parser.py,schema.json}
```

## Error Handling

Fail loud, never corrupt, always recoverable. Every script follows:

1. Never silently swallow errors that could mislead
2. Atomic writes for any file that other scripts read (tempfile + rename)
3. Graceful degradation when SMM is missing (exit 0, no output)
4. `flock` for concurrent access to events.jsonl, with timeout fallback
5. Schema validation at write time, not read time

## Testing

All tests live under `tests/` and run on every commit via lefthook (`lefthook.yml`). The pre-commit hook runs four test suites in parallel:

```bash
# Run everything:
python3 -m unittest discover -s plugins/xp-agents/tests -p "test_*.py" -v

# Run a single suite:
python3 -m unittest discover -s plugins/xp-agents/tests/hooks -p "test_*.py" -v

# Run a single file:
python3 -m unittest plugins/xp-agents/tests/hooks/test_session.py -v

# Run a single test class:
python3 -m unittest plugins/xp-agents/tests/hooks/test_session.py -k TestSessionStart -v
```

### Test layout

```
tests/
├── conftest.py              ← shared helpers: make_event, base classes, input factories
├── hooks/                   ← unit tests for command hooks (from scripts/)
│   ├── test_common.py       ← _common.py core utilities
│   ├── test_common_smm.py   ← _common.py SMM data operations (events, watermarks, conflicts)
│   ├── test_session_start.py ← session_start, retrospective
│   ├── test_session_lifecycle.py ← session_end, pre_compact
│   ├── test_kickoff.py      ← kickoff_gate, kickoff_done
│   ├── test_pre_tool_write.py ← conflicts, TDD order, plan review gate
│   ├── test_pre_tool_bash.py  ← commit security triage gate, file-modification heuristic
│   ├── test_post_tool.py    ← post_tool_use, lint_check, post_tool_exit_plan
│   ├── test_bash.py         ← bash_post_tool hook tests, bash_failure
│   ├── test_bash_parsing.py ← is_test_run, parse_test_results, is_git_commit
│   ├── test_subagent.py     ← subagent_start, subagent_stop, user_prompt_log
│   ├── test_review_cycle.py ← review_cycle_done, subagent review flags
│   ├── test_gates.py        ← security triage markers
│   ├── test_stop_gates.py   ← tdd_stop_gate, find_last_test_signal
│   ├── test_validation.py   ← hooks.json structure and registration
│   ├── test_plugin_integrity.py ← plugin file structure, agent files, skill files
│   ├── test_auto_resolve.py ← auto-resolve logic
│   ├── test_retrospective.py ← retrospective data preparation
│   ├── test_retro_save.py   ← save_retrospective
│   ├── test_markers.py      ← review cycle markers
│   ├── test_lint.py         ← lint detection and execution
│   ├── test_commits.py      ← commit helpers
│   ├── test_coordination.py ← coordination logic
│   ├── test_prompt_nugget.py ← prompt nugget delivery
│   ├── test_subagent_tiers.py ← tiered SubagentStart injection (Explore, Plan, sprint)
│   ├── test_teammate_guide.py ← M14 teammate detection + guide injection
│   ├── test_teammate_hooks.py ← M13 TeammateIdle + TaskCompleted TDD gates
│   ├── test_sprint_review.py ← prepare_review_data, sprint_review_done, preload
│   ├── test_sprint_retro.py  ← sprint retro data prep, preload
│   └── test_spawn_team.py   ← M15 spawn-team preload integration
├── integration/             ← full subprocess pipeline tests
│   ├── test_session.py      ← session lifecycle integration
│   ├── test_core_hooks.py   ← pre/post tool use, lint, bash, subagent integration
│   ├── test_scenarios.py    ← round trips, retro, new event types
│   ├── test_scenarios_lifecycle.py ← full lifecycle, plan review, multi-session
│   ├── test_extended.py     ← simplify gate, security review, commit gate
│   ├── test_maintenance.py  ← repair, migration
│   └── test_scaling.py      ← concurrency, worktrees, benchmarks
├── engine/                  ← SMM engine tests (materialize, read_delta, compact)
│   ├── test_parse.py        ← JSONL parsing, index building
│   ├── test_resolutions.py  ← metadata.resolves, read_events_from
│   ├── test_delta.py        ← watermarks, read_delta, symlink protection
│   ├── test_compact.py      ← compact legacy entry point
│   ├── test_compact_curation.py ← curation-watermark-based compaction
│   ├── test_curation.py     ← prepare_curation_data, retro history
│   ├── test_append_helpers.py ← bulk append, atomic writes, build_event
│   └── test_maintenance.py  ← repair, migration, benchmarks
└── smm/                     ← SMM foundation tests (init.sh, append.sh)
    ├── test_init.py          ← initialization, schema validation
    ├── test_seed.py          ← seed SMM
    ├── test_append.py        ← append integration operations
    ├── test_append_safety.py ← concurrency, validation, symlink protection
    └── test_append_schema.py ← schema.json validation, notifications
```

### Writing new tests

- **Hook unit tests** go in `tests/hooks/`. Import the module, call `run(input_data, smm_dir=self.smm_dir)` directly. Extend `_HookTestCase` for a temp SMM dir with `events.jsonl` and `events.lock`.
- **Integration tests** go in `tests/integration/`. Extend `_IntegrationTestCase` which creates a temp git repo with init.sh. Use `self._run_script("script.py", {...})` to pipe JSON via subprocess, `self._read_events()` to check results, `self._seed_events([...])` to pre-populate.
- **Engine tests** go in `tests/engine/`. Extend `_SMMTestCase` for a temp SMM dir.
- **SMM foundation tests** go in `tests/smm/`. Extend `_TempRepoTestCase` for subprocess tests with init.sh/append.sh.
- Follow TDD: write the test first, watch it fail, then implement.

### Test helpers (all in `tests/conftest.py`)

- `make_event(type, **kwargs)` — creates a valid event dict with defaults
- `_SMMTestCase` / `_HookTestCase` — `setUp` creates temp dir with `events.jsonl` + `events.lock`, `tearDown` cleans up
- `_IntegrationTestCase` — creates temp git repo, inits SMM, provides `_run_script()`, `_read_events()`, `_seed_events()`
- `_TempRepoTestCase` — temp git repo for subprocess tests (init.sh, append.sh)
- `_make_write_input(**overrides)` — canonical Write tool hook input
- `_make_bash_input(command, stdout, **overrides)` — canonical Bash tool hook input
- `_override_settings(overrides)` — context manager for settings.json isolation

## Key Decisions (Don't Revisit)

- Hooks-first — all XP agents are hook handlers
- SMM at `${CLAUDE_PLUGIN_DATA}/{project-id}/smm/` (shared across worktrees)
- Prompt nuggets deliver context at UserPromptSubmit, PostToolUse records to event log
- Quality reviewer is post-simplify skill (courage + drift + debt)
- Retrospective runs at session start, not session end
- Keep/Fix/Try framework with XP values as analytical lenses
- `customer_input` events from UserPromptSubmit
- Plan subagent output reviewed by SubagentStop hook
- Python 3.10+, stdlib only, zero dependencies
- Three-file architecture: events.jsonl + product_spec.md + sprint.md
- Intent and Sprint are separate concerns — strategic/persistent vs tactical/ephemeral
- Interactive skills (sprint-start, product-spec) inline; review/analysis skills forked
- Teammates detected by `is_teammate_by_agent_type()` — custom agent_type exclusion
- No prep script for spawn-team — domain analysis is LLM judgment
- Commit-gated review cycle (not stop-gated) — enforced at commit time via PreToolUse:Bash