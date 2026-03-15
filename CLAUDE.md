# xp-agents Development Guide

## What This Project Is

A Claude Code plugin that enforces XP practices via hooks. Broadcast event log (Shared Mental Model) replaces point-to-point mailboxes. All XP agents are implemented as hook handlers.

Read `ARCHITECTURE.md` before starting any milestone. It is the source of truth for design decisions, hook map, event types, and platform constraints.

## Official Claude Code Docs (check for latest API)

- **Hooks reference**: https://code.claude.com/docs/en/hooks.md
- **Hooks guide**: https://code.claude.com/docs/en/hooks-guide.md
- **Plugins**: https://code.claude.com/docs/en/plugins.md
- **Plugins reference**: https://code.claude.com/docs/en/plugins-reference.md
- **Skills**: https://code.claude.com/docs/en/skills.md
- **Subagents**: https://code.claude.com/docs/en/sub-agents.md
- **Full docs index**: https://code.claude.com/docs/llms.txt

Always verify hook I/O formats against the hooks reference before implementing new hooks. The API evolves.

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
            "type": "agent",
            "prompt": "${CLAUDE_PLUGIN_ROOT}/prompts/navigator.md",
            "agent_type": "xp-navigator"
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
├── BEHAVIORAL_GUIDE.md                ← loaded by session_start.py
├── settings.json                      ← runtime config
├── hooks/hooks.json                   ← all hook registrations
├── scripts/*.py                       ← command hooks
├── agents/*.md                        ← subagent definitions
├── prompts/*.md                       ← agent/prompt hook definitions
├── skills/{smm-protocol,xp-values,pair-programming}/SKILL.md
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
python3 -m unittest plugins/xp-agents/smm/test_smm.py plugins/xp-agents/smm/test_engine.py plugins/xp-agents/scripts/test_hooks.py plugins/xp-agents/scripts/test_integration.py -v

# Run a single suite:
python3 -m unittest plugins/xp-agents/scripts/test_hooks.py -v

# Run a single test class:
python3 -m unittest plugins/xp-agents/scripts/test_hooks.py -k TestUserPromptLog -v
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