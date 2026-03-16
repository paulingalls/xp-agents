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
| **SessionStart** | `source` (startup/resume/compact/clear), `model`, `permission_mode` | `additionalContext` string | Context injected at conversation start. Sets the stage. |
| **UserPromptSubmit** | `prompt` (the user's text) | `additionalContext` OR `{"decision": "block", "reason": "..."}` | Block erases the prompt entirely. Context adds a system reminder. |
| **PreToolUse** | `tool_name`, `tool_input` | `additionalContext`, `permissionDecision` (allow/deny/ask), `updatedInput` | Can modify tool arguments before execution. Can auto-allow or deny tool use. |
| **PermissionRequest** | `tool_name`, `tool_input`, `permission_suggestions` | `{"decision": {"behavior": "allow\|deny", "updatedInput": {...}}}` | Auto-approve or deny permission dialogs. Can modify input. |
| **PostToolUse** | `tool_name`, `tool_input`, `tool_response` | `additionalContext`, `{"decision": "block"}`, `updatedMCPToolOutput` | Tool already ran. Block provides feedback. Can replace MCP tool output. |
| **PostToolUseFailure** | `tool_name`, `tool_input`, `error`, `is_interrupt` | `additionalContext` | Tool already failed. Context-only — cannot block. |
| **Stop** | `last_assistant_message`, `stop_hook_active` | `{"decision": "block", "reason": "..."}` | **Forces agent to continue.** Agent cannot finish until gate is satisfied. Proven pattern for forcing skill invocation. |
| **SubagentStart** | `agent_id`, `agent_type` | `additionalContext` | Context injected into the subagent before it starts. |
| **SubagentStop** | `agent_type`, `last_assistant_message`, `agent_transcript_path` | `{"decision": "block", "reason": "..."}` | Subagent continues with feedback. |
| **TaskCompleted** | `task_id`, `task_subject`, `task_description` | exit 2 + stderr = block completion | Block task completion with feedback. |
| **Notification** | `message`, `title`, `notification_type` | `additionalContext` | Informational only. Cannot block. |
| **PreCompact** | `trigger` (manual/auto), `custom_instructions` | — | Observational only. |
| **PostCompact** | `trigger`, `compact_summary` | — | Observational only. |
| **SessionEnd** | `reason` (clear/logout/exit/etc.) | — | Cleanup only. 1.5s default timeout. |
| **ConfigChange** | `source`, `file_path` | `{"decision": "block", "reason": "..."}` | Block config changes (except policy). |
| **Elicitation** | `mcp_server_name`, `message`, `mode`, `requested_schema` | `{"action": "accept\|decline\|cancel", "content": {...}}` | Respond programmatically to MCP elicitations. |

**Common input fields (all events):** `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, `agent_id`, `agent_type`

**Exit codes:** 0 = success/allow, 2 = block/deny, other = error (action proceeds, stderr logged)

---

## 2. Agent Hooks

**What they are:** Subagents that run in response to hook events. They can inspect files and run commands, then return an allow/block decision.

**When to use:** Judgment calls that require reading code or running commands — checking conventions, verifying output quality, validating against patterns. Use when the decision requires more than deterministic logic but doesn't need the full main agent context.

**Key limitation:** Can only return allow/block. Cannot inject `additionalContext`. Cannot modify tool inputs.

| Aspect | Value |
|--------|-------|
| **Receives** | Hook JSON + limited context |
| **Tools available** | Read, Grep, Glob, Bash, WebFetch, WebSearch (configurable) |
| **Returns** | `{"ok": true}` or `{"ok": false, "reason": "..."}` |
| **Can inject context?** | No — allow/block only |
| **Async support?** | Yes (`"async": true` in hook definition) |

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
- `allowed-tools` can pre-grant permissions (e.g., `Bash(python *)`)
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
| `description` | string | **The only auto-trigger mechanism.** Agent matches this against conversation. |
| `disable-model-invocation` | boolean | If true, only user can invoke via `/name` |
| `user-invocable` | boolean | If false, hides from `/` menu, only agent can invoke |
| `allowed-tools` | string[] | Pre-grant tool permissions (e.g., `Bash(python *)`) |
| `model` | string | Override model for this skill |
| `context` | enum | `fork` = run in isolated subagent (see Forked Skills below) |
| `agent` | string | Subagent type when `context: fork` |
| `argument-hint` | string | Hint shown in autocomplete |
| `hooks` | object | Hook config scoped to this skill's lifecycle |

### Arguments

Skills accept arguments via `/skill-name arg1 arg2`. Available as substitution variables:

| Variable | Value |
|----------|-------|
| `$ARGUMENTS` | All arguments as a single string |
| `$0`, `$1`, ... | Individual positional arguments |
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
- Plugin-defined: `xp-agents:xp-navigator`, `xp-agents:xp-quality-reviewer`, etc.
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
| **Tools available** | Configurable via `tools` field (Read/Grep/Glob baseline, empirically confirmed) |
| **Returns** | Result summary to invoking agent |
| **Trigger** | Agent tool invocation — agent matches `description` against the task |
| **Namespace** | `plugin-name:agent-name` (e.g., `xp-agents:xp-navigator`) |
| **Background** | Caller chooses `run_in_background: true/false` — background agents cannot prompt for permissions |

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
| Agent hooks | Hook definition | Configurable in hook definition |
| Prompt hooks | None (no tools) | N/A |
| Skills (inline) | Main agent's permissions | Yes — `allowed-tools` field |
| Skills (forked) | Agent type defaults | Partially — via `allowed-tools` |
| Plugin subagents | `tools` field in agent def | No — user must approve at runtime |
| Background subagents | User pre-approval at launch | Sort of — user prompted upfront, but can't interact during execution |
