# Plugin Tools — Data Flow Reference

What a Claude Code plugin can ship, what each tool can do, and how data flows between the main agent and each tool.

## Tool Types at a Glance

| Tool | Executor | Purpose |
|------|----------|---------|
| **Command Hook** | External script (subprocess) | Deterministic reactions to events — gate, inject context, record state. Full OS access. |
| **Agent Hook** | Subagent (isolated) | Judgment calls requiring file inspection — verify code, check conventions, validate output. |
| **Prompt Hook** | Haiku (single-turn LLM) | Quick yes/no decisions — lightweight gate without tool access. |
| **Skill (inline)** | Main agent | Extend the main agent's behavior with a prompt — full context, full permissions, full tools. |
| **Skill (forked)** | Subagent (isolated) | Delegate complex work to a subagent with a structured prompt — isolated context, configurable tools. |
| **Plugin Subagent** | Subagent (isolated) | Specialized autonomous agent — invoked by the main agent via the Agent tool when it matches the task. |

---

## 1. Command Hooks

**What they are:** Shell scripts that run as subprocesses in response to hook events. They have full OS access but no conversation context — they only see what's on stdin.

**When to use:** Deterministic logic that shouldn't depend on LLM judgment. Gating actions, injecting context, recording events, running linters, managing state files.

**Key property:** The only tool that can both inject `additionalContext` AND block actions. But additionalContext is advisory — the agent can read it and choose not to act on it. Blocking (`decision: block` or exit 2) is mandatory.

### Data Flow by Event

| Event | What the agent provides (stdin JSON) | What the script can return to the agent | Effect on the agent |
|-------|--------------------------------------|----------------------------------------|---------------------|
| **SessionStart** | `source` (startup/resume/compact/clear), `model`, `permission_mode` | `additionalContext` string, `CLAUDE_ENV_FILE` | Context injected at conversation start. Sets the stage. |
| **UserPromptSubmit** | `prompt` (the user's text) | `additionalContext` OR `{"decision": "block", "reason": "..."}` | Block erases the prompt entirely. Context adds a system reminder. |
| **PreToolUse** | `tool_name`, `tool_input`, `tool_use_id` | `additionalContext`, `permissionDecision` (allow/deny/ask/defer), `updatedInput` | Can modify tool arguments before execution. Can auto-allow or deny tool use. |
| **PermissionRequest** | `tool_name`, `tool_input`, `permission_suggestions` | `{"decision": {"behavior": "allow\|deny", "updatedInput": {...}, "updatedPermissions": [...]}}` | Auto-approve or deny permission dialogs. Can modify input and apply permission rules. |
| **PostToolUse** | `tool_name`, `tool_input`, `tool_response`, `tool_use_id` | `additionalContext`, `{"decision": "block"}`, `updatedMCPToolOutput` | Tool already ran. Block provides feedback. Can replace MCP tool output. |
| **PostToolUseFailure** | `tool_name`, `tool_input`, `error`, `is_interrupt`, `tool_use_id` | `additionalContext` | Tool already failed. Context-only — cannot block. |
| **Stop** | `permission_mode`, `stop_hook_active` | `{"decision": "block", "reason": "..."}` | **Forces agent to continue.** Agent cannot finish until gate is satisfied. |
| **SubagentStart** | `agent_id`, `agent_type` | `additionalContext` | Context injected into the subagent before it starts. **No `metadata` field** — only `agent_id` + `agent_type`. |
| **SubagentStop** | `agent_type`, `last_assistant_message`, `agent_transcript_path`, `agent_id`, `stop_hook_active`, `permission_mode` | `{"decision": "block", "reason": "..."}` | Subagent continues with feedback. |
| **TeammateIdle** | `teammate_name`, `team_name`, `permission_mode` | exit 2 + stderr = block idle, `{"continue": false, "stopReason": "..."}` | Can keep teammates working or stop entirely. |
| **TaskCreated** | `task_id`, `task_subject`, `task_description` (opt), `teammate_name` (opt), `team_name` (opt), `permission_mode` | exit 2 + stderr = block creation | Enforce naming conventions, require descriptions. |
| **TaskCompleted** | `task_id`, `task_subject`, `task_description` (opt), `teammate_name` (opt), `team_name` (opt), `permission_mode` | exit 2 + stderr = block completion | Block task completion with feedback. |
| **Notification** | `message`, `title`, `notification_type` | `additionalContext` | Informational only. Cannot block. |
| **PermissionDenied** | `tool_name`, `tool_input`, `tool_use_id`, `reason` | `{"hookSpecificOutput": {"retry": true}}` | Only fires in auto mode. `retry: true` tells model it may retry. |
| **StopFailure** | Error context (rate_limit, auth, billing, server_error, max_output_tokens, unknown) | — (output ignored) | Observability only. |
| **PreCompact** | `trigger` (manual/auto), `custom_instructions` | — | Observational only. |
| **PostCompact** | `trigger`, `compact_summary` | — | Observational only. |
| **ConfigChange** | `source`, `file_path` | `{"decision": "block", "reason": "..."}` | Block config changes (except policy). |
| **CwdChanged** | `new_cwd` | `CLAUDE_ENV_FILE` | Fires when working directory changes. Useful for direnv integration. |
| **FileChanged** | `file_path`, `change_type` (matcher: filename basename) | `CLAUDE_ENV_FILE` | Fires when watched file changes on disk. |
| **Elicitation** | `mcp_server_name`, `message`, `mode`, `requested_schema` | `{"action": "accept\|decline\|cancel", "content": {...}}` | Respond programmatically to MCP elicitations. |
| **ElicitationResult** | MCP server name + user response | `{"action": "accept\|decline\|cancel", "content": {...}}` | Modify user response before sending to server. exit 2 blocks. |
| **InstructionsLoaded** | `file_path`, `memory_type`, `load_reason`, `globs` (opt) | — | Observability only. Audit logging for CLAUDE.md loads. |
| **WorktreeCreate** | Worktree context | stdout = path, `{"hookSpecificOutput": {"worktreePath": "/path"}}` | Replaces default git behavior. Non-zero exit fails creation. |
| **WorktreeRemove** | Worktree path | — | Non-blocking. Failures logged in debug only. |
| **SessionEnd** | `reason` (clear/logout/exit/etc.) | — | Cleanup only. 1.5s default timeout. |

**Common input fields (all events):** `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, `agent_id`, `agent_type`

**Exit codes:** 0 = success/allow, 2 = block/deny, other = error (action proceeds, stderr logged)

**Universal output fields (all events):**

| Field | Type | Description |
|-------|------|-------------|
| `continue` | boolean | Set to `false` to stop the session entirely (not just block the action). |
| `stopReason` | string | Message when `continue: false`. |
| `suppressOutput` | boolean | Suppress the hook's stdout from being processed. |
| `systemMessage` | string | Notification shown to the **user** (not the agent). |

### Hook Config: `statusMessage`

A `statusMessage` field in the hook definition (in `hooks.json`) sets the spinner text the user sees while the hook runs. Without it, the user sees a generic spinner.

```json
{
  "type": "command",
  "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/my_hook.py",
  "statusMessage": "Running my check..."
}
```

### Hook Output: `systemMessage`

A `systemMessage` field in the hook's stdout JSON shows a notification to the **user** after the hook completes. This is separate from `additionalContext`, which only the agent sees.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "Context only the agent sees."
  },
  "systemMessage": "Notification the user sees."
}
```

Works with blocking output too:

```json
{
  "decision": "block",
  "reason": "Detailed reason for the agent.",
  "systemMessage": "Short message for the user."
}
```

| Field | Audience | Purpose |
|-------|----------|---------|
| `additionalContext` | Agent only | Inject context into the conversation (advisory) |
| `systemMessage` | User only | Show a notification in the UI |
| `statusMessage` (config) | User only | Spinner text while the hook runs |

---

## 2. Agent Hooks

**What they are:** Subagents that run in response to hook events. They can inspect files and run commands, then return an allow/block decision.

**When to use:** In theory, judgment calls that require reading code or running commands. **In practice, agent hooks are currently broken platform-wide** — they crash with "Messages are required for agent hooks. This is a bug." on all events tested (PostToolUse, UserPromptSubmit). This is a Claude Code platform issue, not fixable from the plugin side. Use command/prompt hooks or plugin subagents (wrapped in forked skills) instead.

**Key limitation:** Can only return allow/block. Cannot inject `additionalContext`. Cannot modify tool inputs. Currently non-functional due to platform bug.

| Aspect | Value |
|--------|-------|
| **Receives** | Hook JSON + limited context |
| **Tools available** | Documented as full inheritance, but crashes before spawning |
| **Returns** | `{"ok": true}` or `{"ok": false, "reason": "..."}` |
| **Can inject context?** | No — allow/block only |
| **Async support?** | Yes (`"async": true` in hook definition) |
| **Status** | **Broken** — crashes on all events with "Messages are required" error |

---

## 3. Prompt Hooks

**What they are:** Single-turn LLM evaluations (Haiku) that make quick judgment calls without tool access.

**When to use:** Lightweight yes/no decisions where you need LLM reasoning but don't need to inspect files. Cheaper and faster than agent hooks.

**Key limitation:** No tool access at all. Cannot read files, run commands, or access any external state. Just reasons over the hook JSON and prompt.

| Aspect | Value |
|--------|-------|
| **Receives** | Hook JSON, evaluated by Haiku |
| **Tools available** | None |
| **Returns** | `{"ok": true}` or `{"ok": false, "reason": "..."}` |
| **Can inject context?** | No — allow/block only |

---

## 4. Skills (Inline)

**What they are:** Prompt files (`SKILL.md`) that get loaded into the main agent's context. The main agent executes the instructions directly — no isolation, no delegation.

**When to use:** Extending the main agent's behavior with specific instructions. Best when the task needs full conversation context, full tool access, and user interaction (e.g., AskUserQuestion). The skill is "just a prompt" — the main agent does the work.

**Key properties:**
- The main agent already has all context (SMM state, conversation history, etc.)
- `!`command`` provides deterministic pre-execution the agent cannot skip
- `allowed-tools` can pre-grant permissions (e.g., `Bash(python *)`) — this also covers `!` command permissions, which go through the same Bash permission check as user commands. Use `Bash(*/skills/*/scripts/*)` to pre-approve all skill preload scripts
- `description` field is the **only** mechanism for auto-triggering

| Aspect | Value |
|--------|-------|
| **Receives** | Main agent's full context + skill body + `$ARGUMENTS` |
| **Deterministic setup** | `!`command`` runs before agent sees skill content — guaranteed execution |
| **Executor** | Main agent itself |
| **Tools available** | Main agent's full tools, constrainable via `allowed-tools` |
| **Returns** | Nothing separate — agent continues with skill instructions loaded |
| **Trigger** | User types `/skill-name` OR agent auto-matches on `description` field |
| **Auto-trigger control** | `disable-model-invocation: true` = user-only. `user-invocable: false` = agent-only. |

### Skill Frontmatter Fields

| Field | Type | Purpose |
|-------|------|---------|
| `name` | string | Slash command name (kebab-case, max 64 chars) |
| `description` | string | **The only auto-trigger mechanism.** Agent matches this against conversation. Truncated at 250 chars in listing. |
| `disable-model-invocation` | boolean | If true, only user can invoke via `/name` |
| `user-invocable` | boolean | If false, hides from `/` menu, only agent can invoke |
| `allowed-tools` | string[] | Pre-grant tool permissions (e.g., `Bash(python *)`) |
| `model` | string | Override model for this skill |
| `effort` | enum | Override effort level: `low`, `medium`, `high`, `max` |
| `context` | enum | `fork` = run in isolated subagent (see Forked Skills below) |
| `agent` | string | Subagent type when `context: fork` |
| `argument-hint` | string | Hint shown during autocomplete (e.g., `[issue-number]`) |
| `paths` | string/list | Glob patterns limiting auto-activation to matching files |
| `hooks` | object | Hook config scoped to this skill's lifecycle |
| `shell` | enum | `bash` (default) or `powershell` for `!` commands |

### Arguments

Skills accept arguments via `/skill-name arg1 arg2`. Available as substitution variables:

| Variable | Value |
|----------|-------|
| `$ARGUMENTS` | All arguments as a single string |
| `$ARGUMENTS[N]` | Access specific argument by 0-based index |
| `$0`, `$1`, ... | Shorthand for `$ARGUMENTS[N]` |
| `${CLAUDE_SESSION_ID}` | Current session ID |
| `${CLAUDE_SKILL_DIR}` | Absolute path to the skill's directory |

Arguments let hooks, other skills, or the agent itself pass structured data into a skill invocation.

### Dynamic Context Injection

```markdown
---
name: my-skill
---
Current state:
!`cat /path/to/state.json`

Instructions based on the above state...
```

The `!`command`` output is injected **before** the agent sees the skill content. The agent cannot skip or ignore this execution. Use for state checks, setup, or pre-loading data.

### Scoped Hooks

The `hooks` field attaches hooks that **only fire while the skill is active**. This means a skill can have its own gates, context injection, or validation that don't affect the rest of the session.

```yaml
---
name: deploy
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: "${CLAUDE_SKILL_DIR}/validate-deploy.sh"
  Stop:
    - hooks:
        - type: command
          command: "${CLAUDE_SKILL_DIR}/deploy-checklist.sh"
---
```

Use cases:
- A skill with its own Stop gate (must complete checklist before finishing)
- Extra validation on tool use only during this skill's execution
- Skill-specific context injection via PreToolUse

### Self-Contained Skill Directories

Skills can carry their own scripts and supporting files, all scoped via `${CLAUDE_SKILL_DIR}`:

```
skills/my-skill/
├── SKILL.md              ← prompt + frontmatter (hooks, allowed-tools, etc.)
├── scripts/
│   ├── setup.sh          ← called by !`command` for deterministic pre-execution
│   ├── validate.sh       ← called by scoped hooks
│   └── do_work.sh        ← called by skill body instructions
└── reference.md          ← supporting docs, loaded on demand by the agent
```

This keeps each skill self-contained — its prompt, scripts, hooks, and reference material all live together. No cross-referencing into shared directories. The skill is a deployable unit within the plugin.

---

## 5. Skills (Forked)

**What they are:** Skills with `context: fork` that run in an isolated subagent instead of the main agent.

**When to use:** Complex delegated work that doesn't need the main conversation's context. Research tasks, analysis, code generation that should run independently.

**Key difference from inline:** The subagent does NOT have the main agent's conversation history. It only sees the skill body and `!`command`` output.

**Key property:** The `agent` field can reference **any** subagent type — built-in or custom:
- Built-in: `Explore`, `Plan`, `general-purpose`
- Plugin-defined: `xp-agents:xp-retrospective`, `xp-agents:xp-plan-reviewer`, etc.
- User-defined: any agent in `~/.claude/agents/` or `.claude/agents/`

This means a skill can be a curated front-end (prompt + arguments + `!`command`` + scoped hooks) that delegates execution to an existing specialized agent. The skill controls *what* and *when*; the agent controls *how*.

| Aspect | Value |
|--------|-------|
| **Receives** | Skill body + `!`command`` output + `$ARGUMENTS` (no conversation history) |
| **Executor** | Any subagent (set by `agent` field — built-in, plugin, or user-defined) |
| **Tools available** | Determined by agent type, constrainable via `allowed-tools` |
| **Returns** | Result summary to main agent |
| **Trigger** | Same as inline skills |

---

## 6. Plugin Subagents

**What they are:** Agent definitions (`agents/*.md`) that the main agent can invoke via the Agent tool. They run in isolated context with their own tool set.

**When to use:** Specialized autonomous agents for specific task types — code review, research, testing. Best when the task is self-contained and the agent can work independently.

**Key property:** Triggered by `description` matching in the Agent tool — the main agent decides when to invoke based on the task at hand. This is similar to skill description matching but happens at the Agent tool level.

| Aspect | Value |
|--------|-------|
| **Receives** | Agent prompt + task description from invoking agent |
| **Executor** | Isolated subagent |
| **Tools available** | Configurable via `tools` field. Use `disallowedTools` for denylist alternative. |
| **Returns** | Result summary to invoking agent |
| **Trigger** | Agent tool invocation — agent matches `description` against the task |
| **Namespace** | `plugin-name:agent-name` (e.g., `xp-agents:xp-plan-reviewer`) |
| **Background** | Caller chooses `run_in_background: true/false` — background agents cannot prompt for permissions |
| **As teammate type** | Subagent definitions can be referenced when spawning teammates — teammate gets `tools`, `model`, and body appended to system prompt |

### Subagent Frontmatter Fields

| Field | Type | Purpose |
|-------|------|---------|
| `name` | string | Unique identifier (lowercase, hyphens) |
| `description` | string | When to delegate to this subagent |
| `tools` | string/list | Allowlist of tools. Inherits all if omitted. |
| `disallowedTools` | string/list | Denylist — tools removed from inherited set. Applied before `tools`. |
| `model` | enum | `sonnet`, `opus`, `haiku`, full model ID, or `inherit` (default) |
| `permissionMode` | enum | `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`. **Not supported for plugin agents.** |
| `maxTurns` | number | Maximum agentic turns before subagent stops |
| `skills` | list | Skills preloaded into subagent context at startup (full content injected) |
| `mcpServers` | list | MCP servers scoped to this subagent. Inline defs or name references. **Not supported for plugin agents.** |
| `hooks` | object | Scoped hooks — only fire while this subagent is active. **Not supported for plugin agents.** |
| `memory` | enum | Persistent memory scope: `user`, `project`, `local`. Cross-session learning. |
| `background` | boolean | Always run as background task. Default: false. |
| `effort` | enum | Override effort level: `low`, `medium`, `high`, `max` (Opus 4.6 only). |
| `isolation` | enum | Set to `worktree` for isolated git worktree. Auto-cleaned if no changes. |
| `color` | enum | Display color: red, blue, green, yellow, purple, orange, pink, cyan. |
| `initialPrompt` | string | Auto-submitted first user turn when running as main session agent (`--agent`). |

**Plugin agent constraint:** `hooks`, `mcpServers`, and `permissionMode` are **silently ignored** for plugin subagents. Use global `hooks.json` instead. To use these fields, copy the agent to `.claude/agents/` or `~/.claude/agents/`.

---

## Data Flow Patterns

### Context Injection (advisory)
```
Command Hook → additionalContext → Main Agent sees it as system-reminder
```
The agent **can ignore** this. Use for nudges, reminders, state information.

### Blocking (mandatory)
```
Command Hook → decision: block → Agent MUST respond before proceeding
```
The agent **cannot ignore** this. Use for gates that force specific behavior (e.g., Stop hooks).

### Deterministic Pre-execution
```
Skill !`command` → output injected → Agent sees result as part of skill content
```
The command **always runs**. The agent sees the output but didn't choose to run it. Use for guaranteed setup.

### Description Auto-matching (probabilistic)
```
Skill/Subagent description → Agent matches against current task → May or may not invoke
```
**Not guaranteed.** The agent decides based on relevance. Improve odds with specific, keyword-rich descriptions.

---

## Permission Boundaries

| Tool | Permission Source | Can Pre-grant? |
|------|------------------|----------------|
| Command hooks | OS-level (subprocess) | N/A — always has full OS access |
| Agent hooks | Hook definition | Configurable in hook definition (but currently broken — see above) |
| Prompt hooks | None (no tools) | N/A |
| Skills (inline) | Main agent's permissions | Yes — `allowed-tools` field (also covers `!` command permissions) |
| Skills (forked) | Agent type defaults | Partially — via `allowed-tools` (use `Bash(*/skills/*/scripts/*)` for preloads) |
| Plugin subagents | `tools` field in agent def | No — user must approve at runtime |
| Background subagents | User pre-approval at launch | Sort of — user prompted upfront, but can't interact during execution |
