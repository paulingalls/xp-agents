# xp-agents Development Guide

## What This Project Is

A Claude Code plugin that enforces XP practices via hooks. Broadcast event log (Shared Mental Model) replaces point-to-point mailboxes. All XP agents are implemented as hook handlers.

Read `ARCHITECTURE.md` before starting any milestone. It is the source of truth for design decisions, hook map, event types, and platform constraints.

## Build Order

Follow `MILESTONES.md` sequentially. Each milestone's acceptance criteria must pass before moving to the next. The milestones are: SMM Foundation → SMM Engine → Core Hooks (4 sub-milestones) → Agent Hooks Quality/Navigation → Agent Hooks Session Lifecycle → CLAUDE.md & Skills → Integration Testing → Hardening.

## Coding Standards

**Python 3.10+, stdlib only.** No external packages. No pip. No virtualenv. Every script must run with just `python3` on PATH.

Use `match/case` for tool_name routing, event type handling, and hook input parsing. Use type hints. Use `pathlib` over `os.path`.

All scripts start with `#!/usr/bin/env python3`.

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

### Command Hook Output (stdout, exit 0)
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

### Blocking (exit 2)
```python
print("Explanation of why this is blocked", file=sys.stderr)
sys.exit(2)
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
# SMM lives at: ~/.claude/xp-agents/{project-id}/smm/
```

All scripts resolve the SMM path this way. Never hardcode paths. Never use `.claude/smm/` — the SMM is at user level, not project level.

## Event Appending

Use `smm/append.sh` for all event writes. Never write directly to `events.jsonl`.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "$AGENT_ID" \
  --content "Description here" \
  --working-on '["src/api/users.ts"]'
```

## Hook Registration (hooks.json)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/pre_tool_use.py"
          }
        ]
      },
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/navigator_gate.py"
          },
          {
            "type": "agent",
            "prompt": "${CLAUDE_PLUGIN_ROOT}/prompts/navigator.md"
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

**PostToolUse `additionalContext` may not work** — write to event log instead. The next PreToolUse delivers it. See architecture doc Platform Constraints section for details and GitHub issue references.

**PostToolUse agent hooks should be async** (`"async": true`) — feedback goes through event log anyway, no need to block.

## File Structure

```
plugins/xp-agents/
├── .claude-plugin/plugin.json
├── CLAUDE.md                          ← the plugin's CLAUDE.md (milestone 6), NOT this file
├── settings.json
├── skills/{smm-protocol,xp-values,pair-programming}/SKILL.md
├── hooks/hooks.json                   ← all hook registrations
├── scripts/*.py                       ← command hooks
├── prompts/*.md                       ← agent/prompt hook definitions
└── smm/{init.sh,append.sh,materialize.py,read_delta.py,schema.json}
```

## Error Handling

Fail loud, never corrupt, always recoverable. Every script follows:

1. Never silently swallow errors that could mislead
2. Atomic writes for any file that other scripts read (tempfile + rename)
3. Graceful degradation when SMM is missing (exit 0, no output)
4. `flock` for concurrent access to events.jsonl, with timeout fallback
5. Schema validation at write time, not read time

## Testing

All tests run on every commit via lefthook (`lefthook.yml`). The pre-commit hook runs four test suites in parallel:

```bash
# Run everything (what pre-commit does):
python3 -m unittest smm/test_smm.py smm/test_engine.py scripts/test_hooks.py scripts/test_integration.py -v

# Run a single suite:
python3 -m unittest scripts/test_hooks.py -v

# Run a single test class:
python3 -m unittest scripts/test_hooks.py -k TestUserPromptLog -v
```

### Test suites

| Suite | File | What it tests |
|-------|------|---------------|
| SMM Foundation | `smm/test_smm.py` | init.sh, append.sh, `_append_impl.py`, schema, concurrency, notifications |
| SMM Engine | `smm/test_engine.py` | materialize.py, read_delta.py. Provides `_SMMTestCase` base class and `make_event()` helper used by all other suites |
| Hook unit tests | `scripts/test_hooks.py` | `_common.py` and all command hook `run()` functions with temp SMM dirs (no subprocess) |
| Integration tests | `scripts/test_integration.py` | Full subprocess pipeline: creates temp git repo, runs init.sh, pipes JSON to each script, verifies events on disk and stdout/stderr/exit codes |

### Writing new tests

- **Unit tests** go in `scripts/test_hooks.py`. Import the module, call `run(input_data, smm_dir=self.smm_dir)` directly. Extend `_HookTestCase` (alias for `_SMMTestCase`) for a temp SMM dir with `events.jsonl` and `events.lock`.
- **Integration tests** go in `scripts/test_integration.py`. Extend `_IntegrationTestCase` which creates a temp git repo with init.sh. Use `self._run_script("script.py", {...})` to pipe JSON via subprocess, `self._read_events()` to check results, `self._seed_events([...])` to pre-populate.
- **SMM/engine tests** go in `smm/test_smm.py` or `smm/test_engine.py`.
- Follow TDD: write the test first, watch it fail, then implement.

### Test helpers

- `make_event(type, **kwargs)` — creates a valid event dict with defaults (from `test_engine.py`, imported everywhere)
- `_SMMTestCase` / `_HookTestCase` — `setUp` creates temp dir with `events.jsonl` + `events.lock`, `tearDown` cleans up
- `self._write_events([...])` — seed events into the temp SMM
- `self._read_events()` — parse events back from disk

## Key Decisions (Don't Revisit)

- Hooks-first — all XP agents are hook handlers
- SMM at `~/.claude/xp-agents/{project-id}/smm/` (user level, shared across worktrees)
- Install at user scope (`--scope user`)
- PreToolUse delivers context, PostToolUse records to event log
- Navigator is required (PreToolUse agent hook), not opt-in
- Quality reviewer is PostToolUse async agent hook (combined courage + simplicity)
- Retrospective runs at session start, not session end
- Keep/Fix/Try framework with XP values as analytical lenses
- `customer_input` events from UserPromptSubmit
- Plan subagent output reviewed by SubagentStop hook
- Python 3.10+, stdlib only, zero dependencies