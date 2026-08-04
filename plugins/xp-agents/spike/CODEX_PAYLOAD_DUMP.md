# Codex payload dump — story-003

**Throwaway.** Deleted at sprint close with the rest of the rig; story-007 reads
it before then. Observed on `codex-cli 0.146.0`, model `gpt-5.6-sol`.

The raw payload corpus is deliberately **not** in git. It carries absolute home
paths, session UUIDs, transcript paths, verbatim prompts and an unreleased model
id, and `--no-ff` merges mean a committing commit stays reachable from main
forever — so deletion at close would not have contained it. The tables below are
generated from that out-of-tree corpus by `tabulate_fields.py`; re-run with
`python3 plugins/xp-agents/spike/tabulate_fields.py`.

## The three decisive fields

| field | verdict |
|---|---|
| `agent_type` / `agent_id` | **Present, but the value does not discriminate.** `'default'` for a Codex subagent, never our agent name. `_common.is_xp_agent` is `agent_type.startswith("xp-")`, so it returns False and **recursion prevention never fires**. Absent entirely on top-level tool events, `'default'` on subagent-scoped ones — hence three states below. |
| `stop_hook_active` | **Present AND functional.** Reads False on a turn's first Stop, flips True after the first block and stays True. All four Stop gates bypass on True, so they release correctly. Gap #31's premise ("no known analogue") is falsified twice over. |
| `source` | **Present** on SessionStart, value `'startup'`. |

## Corrections this dump makes to the compatibility table

- The table lists 14 fields but omits `session_id`, which shipped code reads in
  four places (`hook_liveness.payload_session_id`, `housekeeping_flight` x3,
  `bash_post_tool`). It is **15**.
- `tool_name` for an edit is verbatim **`apply_patch`**. The matcher's `Edit` and
  `Write` alternatives are dead names on this harness.
- `tool_input.command` is present for both Bash and apply_patch as the plan said,
  but differs **in kind**: a shell command for Bash, patch TEXT for apply_patch.
  A path extractor must parse the `*** Update File:` / `*** Add File:` /
  `*** Delete File:` lines, not treat the value as a command.
- `tool_response` arrives as a plain string. Not a break — `bash_post_tool.py`
  already handles dict-or-string.
- A **failed** tool call fires `PreToolUse` and then **nothing**: no
  `PostToolUse`, and `PostToolUseFailure` is not a recognised Codex event. 4 of 5
  `tool_use_id`s paired; the failed `apply_patch` did not.

## A real apply_patch payload, verbatim

```json
{
  "session_id": "019fce2a-0654-7b80-9291-9b973e956eeb",
  "turn_id": "019fce2a-0704-7fb0-aec4-02e48a71fa17",
  "transcript_path": "<redacted>",
  "cwd": "<scratch>/proj",
  "hook_event_name": "PreToolUse",
  "model": "gpt-5.6-sol",
  "permission_mode": "bypassPermissions",
  "tool_name": "apply_patch",
  "tool_input": {
    "command": "*** Begin Patch\n*** Update File: <home>/.xp-agents-spike/run-E/proj/notes.txt\n@@\n-before\n+after\n*** End Patch"
  },
  "tool_use_id": "exec-35c97476-550c-4288-b467-6924408f18bd"
}
```

## Field presence by event

| event | cwd | tool_input | agent_type | agent_id | stop_hook_active | tool_name | source | tool_response | prompt | error | reason | name | is_interrupt | exit_code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PermissionRequest | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed |
| PostCompact | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed |
| PostToolUse | always | always | some-firings | some-firings | never | always | never | always | never | never | never | never | never | never |
| PostToolUseFailure | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed |
| PreCompact | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed |
| PreToolUse | always | always | some-firings | some-firings | never | always | never | never | never | never | never | never | never | never |
| SessionEnd | always | never | never | never | never | never | never | never | never | never | always | never | never | never |
| SessionStart | always | never | never | never | never | never | always | never | never | never | never | never | never | never |
| Stop | always | never | never | never | always | never | never | never | never | never | never | never | never | never |
| SubagentStart | always | never | always | always | never | never | never | never | never | never | never | never | never | never |
| SubagentStop | always | never | always | always | always | never | never | never | never | never | never | never | never | never |
| TaskCompleted | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed |
| TeammateIdle | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed |
| UserPromptSubmit | always | never | never | never | never | never | never | never | always | never | never | never | never | never |
| WorktreeCreate | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed | not-observed |

## Fields Codex sends that our table does not list

- `agent_transcript_path` — on SubagentStop
- `last_assistant_message` — on Stop, SubagentStop
- `model` — on PostToolUse, PreToolUse, SessionStart, Stop, SubagentStart, SubagentStop, UserPromptSubmit
- `permission_mode` — on PostToolUse, PreToolUse, SessionStart, Stop, SubagentStart, SubagentStop, UserPromptSubmit
- `session_id` — on PostToolUse, PreToolUse, SessionEnd, SessionStart, Stop, SubagentStart, SubagentStop, UserPromptSubmit
- `tool_use_id` — on PostToolUse, PreToolUse
- `transcript_path` — on PostToolUse, PreToolUse, SessionEnd, SessionStart, Stop, SubagentStart, SubagentStop, UserPromptSubmit
- `turn_id` — on PostToolUse, PreToolUse, Stop, SubagentStart, SubagentStop, UserPromptSubmit

## Decisive fields, in firing order

- run-A2 SessionStart: source='startup'
- run-A2 UserPromptSubmit: (none present)
- run-A2 PreToolUse: (none present)
- run-A2 PostToolUse: (none present)
- run-A2 PreToolUse: (none present)
- run-A2 PostToolUse: (none present)
- run-A2 PreToolUse: (none present)
- run-A2 PostToolUse: (none present)
- run-A2 SubagentStart: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PreToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PostToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PreToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PostToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PreToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PostToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PreToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PostToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PreToolUse: (none present)
- run-A2 PostToolUse: (none present)
- run-A2 SubagentStop: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1' stop_hook_active=False
- run-A2 PreToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 PostToolUse: agent_type='default' agent_id='019fcde1-5418-7df3-8212-ac29186ffcf1'
- run-A2 Stop: stop_hook_active=False
- run-A2 SessionEnd: (none present)
- run-D SessionStart: source='startup'
- run-D UserPromptSubmit: (none present)
- run-D PreToolUse: (none present)
- run-D PostToolUse: (none present)
- run-D Stop: stop_hook_active=False
- run-D SessionEnd: (none present)
- run-E SessionStart: source='startup'
- run-E UserPromptSubmit: (none present)
- run-E PreToolUse: (none present)
- run-E PostToolUse: (none present)
- run-E PreToolUse: (none present)
- run-E PreToolUse: (none present)
- run-E PostToolUse: (none present)
- run-E PreToolUse: (none present)
- run-E PostToolUse: (none present)
- run-E PreToolUse: (none present)
- run-E PostToolUse: (none present)
- run-E Stop: stop_hook_active=False
- run-E SessionEnd: (none present)
- run-F SessionStart: source='startup'
- run-F UserPromptSubmit: (none present)
- run-F Stop: stop_hook_active=False
- run-F Stop: stop_hook_active=True
- run-F Stop: stop_hook_active=True
- run-F Stop: stop_hook_active=True
- run-F SessionEnd: (none present)
