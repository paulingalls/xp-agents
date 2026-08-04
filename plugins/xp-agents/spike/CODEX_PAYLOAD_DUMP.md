# Codex payload dump — story-003

**Throwaway.** Deleted at sprint close with the rest of the rig; story-007 reads
it before then. Observed on `codex-cli 0.146.0`, model `gpt-5.6-sol`.

The raw payload corpus is deliberately **not** in git. It carries absolute home
paths, session UUIDs, transcript paths, verbatim prompts and an unreleased model
id, and `--no-ff` merges mean a committing commit stays reachable from main
forever — so deletion at close would not have contained it. The tables below are
generated from that out-of-tree corpus by `tabulate_fields.py`; re-run with
`python3 plugins/xp-agents/spike/tabulate_fields.py`. It refuses (non-zero, with
the expected glob) rather than emitting an all-`not-observed` table when it finds
no corpus, because those two look identical on the page.

The generated "Runs that produced no captures" section names `run-C`. That is a
finding, not a loss: run-C is story-002's **untrusted-plugin control**, whose
hooks were skipped silently, so zero captures is its result. Any other run
appearing there would be a layout mistake — which is why the section names runs
instead of dropping them.

## Rig state a later story inherits

Isolating emitters for the `apply_patch` capture meant unwiring two SessionStart
entries, and they are **still unwired**: `scripts/session_start.py` (the real
handler, which writes the heartbeat) and `spike/_inject_marker.py` (the
context-injection instrument). Only `_dump_payload.py` and `_probe_resolve.py`
remain registered. Whoever needs either back re-adds it to the `SessionStart`
array in `hooks/hooks.codex.json` **and bumps `.codex-plugin/plugin.json`** — the
plugin cache is version-keyed, so without a bump the run silently executes the
previously cached copy. Forgetting the re-add is detectable rather than silent:
the injector records every marker it mints, so an absent
`injected_markers.jsonl` means "never ran", not "injection failed".

## The three decisive fields

| field | verdict |
|---|---|
| `agent_type` / `agent_id` | **Present, but the value does not discriminate.** `'default'` for a Codex subagent, never our agent name. `_common.is_xp_agent` is `agent_type.startswith("xp-")`, so it returns False and **recursion prevention never fires**. Absent entirely on top-level tool events, `'default'` on subagent-scoped ones — hence three states below. |
| `stop_hook_active` | **Present AND functional.** Reads False on a turn's first Stop, flips True after the first block and stays True. All four Stop gates bypass on True, so they release correctly. Gap #31's premise ("no known analogue") is falsified twice over. |
| `source` | **Present** on SessionStart, value `'startup'`. |

### The liveness caveat story-007 must not miss

`stop_hook_active` working does **not** mean liveness works. Story-002 measured a
separate, negative finding that belongs next to the positive one (concern
`27a3f697f1b0`): **session-scoped liveness never engages on Codex.** The heartbeat
is *written* keyed on the payload `session_id`, but `check_liveness` *reads* from
the environment — and Codex exports none of `XP_SESSION_ID` / `CODEX_THREAD_ID` /
`CLAUDE_CODE_SESSION_ID` to hook processes. So the read misses the session-scoped
marker and degrades to time-only, where any sibling heartbeat under the 4-hour
staleness window reads live.

Consequence: on a **shared** SMM root, an unenforced Codex session started within
four hours of an enforced one reports **LIVE**. Story-002's untrusted run only
reported honestly because every run used its own scratch root. This is recorded in
the SMM, but it is written here too because the rig is deleted at sprint close and
a commit message is not an input story-007 reads.

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

## Runs that produced no captures

- run-C

---

# story-010 — hook-side skill-preload injection

**Verdict: it works end to end.** The customer's design — a hook reads the skill's
identity from its own payload, runs that preload itself, injects the result — is
viable on this harness.

The handle is an accident of the very defect it works around. Codex skills are not
tool calls, so there is no pre-invocation skill event. But Codex has the **model
read `SKILL.md` with a shell command**, so the skill's identity arrives as
`tool_input.command` on `PreToolUse` — an event that accepts injected context.

## What was proven, and how it was made falsifiable

| Leg | Result |
|---|---|
| Identity in the payload | `tool_input.command` carries `/skills/<name>/SKILL.md`. Verbatim field name; extracted across `sed`/`cat`/`head`/`python` shapes and all 16 skills. |
| Injection reaches the model | Marker minted in-hook (`uuid4`), never in the prompt. Model reported it byte-identical. |
| Control | Handler wired with injection **suppressed** — marker still recorded to disk, model answered **NO**. Records also sat outside every `--add-dir` path, so the sandboxed shell could not read them. |
| End to end | Model quoted the seeded Debt id `0f0044d8aae9`, Concern id `4c057451bdbe` and nonce `ZEPHYR-QUARTZ-7741` from 477 injected bytes of real preload output. None appeared in the prompt. |
| The negative | No shipped `SKILL.md` instructs a model to run a preload — story-009 reverted that edit. So state arriving can only be hook delivery. |

## Requirements a shipped version must honour

Each was found the hard way, and each fails **quietly** — exit 0, no error, an
injection that looks successful.

1. **Run the preload in the SESSION's cwd, not the skill dir.** Preloads resolve
   the shared model by hashing the git common dir of their cwd, so running one
   under the plugin cache resolves a *different project's* state. Measured: 75
   bytes of an empty project instead of 477 of the right one. The E2E nonce caught
   this; reasoning did not.
2. **Run the command the skill's own `!` line names.** 14 of 16 say
   `scripts/preload.sh`, one takes `--consume-gate`, one is
   `check_session_needs.sh`. A hardcoded filename is correct on 14 and wrong on 2
   — one of them the most-used skill.
3. **Once per skill per session.** A chunk-read fires `PreToolUse` repeatedly (14
   firings across two skills in the corpus), and `xp-assign`'s preload *consumes*
   a gate marker — so a naive handler burns one gate per chunk.
4. **A heartbeat must exist first.** The shipped preload refuses with
   "Hook Runtime: not live — skill context withheld" when none is found, and the
   injected payload becomes that refusal rather than state.
5. **Constrain the resolved dir under the plugin root** before executing, since
   the command comes out of a file whose path arrived in a payload.

## The main risk

**The handle depends on the model reading `SKILL.md` through a shell command.** If
Codex ever delivers skill bodies without a shell read, or the model uses a
non-shell read tool, `PreToolUse:Bash` stops carrying the identity and the
mechanism silently stops firing — silently, because "no marker" and "no injection"
look identical. Every read observed so far went through `/bin/zsh -lc`.

## Cost of the alternative, if this is not adopted

story-009's in-body fallback, measured from its own reverted commit: **+227 bytes
per skill × 16 = 3,632 bytes**. The binding cost is budgets, not bytes — **6 of 16
would breach their recorded per-skill cap**: `xp-review-plan` (short 117),
`xp-system-context` (113), `xp-sprint-close` (81), `xp-free-close` (79),
`xp-sprint-review` (74), `xp-story-close` (41). And it still rests on the model
volunteering to run a command it read in a file.
