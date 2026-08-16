---
name: xp-system-context
description: >-
  Create or update system_context.json: analyse the codebase to describe the
  product, architecture and technical constraints.
effort: high
allowed-tools:
  - Read
  - Glob
  - Grep
  - Agent
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/smm/system_context_cli.py *)
---

# System Context

> **Sequential discipline.** Spawn the xp-system-analyzer subagent once, wait
> for it to complete, then report back — never batch the spawn with a step
> that depends on it, and never spawn it more than once.

The injected preload state names `SMM_DIR` and `MODE=create|update` (plus
`SYSTEM_CONTEXT=<path>` when `MODE=update`).

## Step 1: Spawn the Analyzer (single unconditional spawn)

Spawn `xp-agents:xp-system-analyzer` unconditionally, threading the
preload's state into its prompt:

```
Agent(
  subagent_type: "xp-agents:xp-system-analyzer",
  prompt: "SMM_DIR=<SMM_DIR>\nMODE=<MODE>\nSYSTEM_CONTEXT=<path, or omit in create mode>\n\nAnalyze the codebase and <create|update> system_context.json per your instructions."
)
```

Wait for the subagent to complete; its summary returns as a tool result.

If you are the main agent and see this: do not do this work yourself — the
analysis must run in the xp-system-analyzer subagent's own isolated context,
not merged into yours. The subagent's tool result is NOT visible to the
user — you must output its key findings as text in your response.

## Step 2: Report Back

Concise summary: what the system context covers, whether it was created or
updated, and any gaps or uncertainties the subagent flagged.
