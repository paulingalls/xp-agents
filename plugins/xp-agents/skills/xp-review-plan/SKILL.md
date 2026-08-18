---
name: xp-review-plan
description: >-
  Review the current plan: size, TDD ordering, milestone boundaries,
  decision conflicts. Use after planning completes.
effort: high
allowed-tools:
  - Agent
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
---

# Review Plan

> **Sequential discipline.** Spawn the xp-plan-reviewer subagent once, wait
> for it to complete, then report its findings back — never batch the spawn
> with a step that depends on it, and never spawn it more than once.

The injected preload state names `SMM_DIR`, and either `PLAN_FILE_ERROR` (no
valid plan to review) or `PLAN_FILE`/`PLAN_SOURCE` plus, when they exist,
`SMM_FILE`, `SPRINT_FILE`, `SYSTEM_CONTEXT_RENDERED`.

## Step 1: Handle a Misfire

If `PLAN_FILE_ERROR` is present, report it verbatim to the user and stop —
do not spawn the reviewer.

## Step 2: Spawn the Reviewer (single unconditional spawn)

Otherwise, spawn `xp-agents:xp-plan-reviewer` unconditionally, threading
every preload var the preload emitted into its prompt:

```
Agent(
  subagent_type: "xp-agents:xp-plan-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\nPLAN_FILE=<PLAN_FILE>\nPLAN_SOURCE=<PLAN_SOURCE>\nSMM_FILE=<path, or omit>\nSPRINT_FILE=<path, or omit>\nSYSTEM_CONTEXT_RENDERED=<path, or omit>\n\nReview the plan per your instructions and report your full findings."
)
```

Wait for the subagent to complete; its findings return as a tool result.

If you are the main agent and see this: do not do this work yourself — the
review must run in the xp-plan-reviewer subagent's own isolated context, not
merged into yours. The subagent's result is a tool result, which is NOT
visible to the user — you must output its full findings, including the four
Final Message blocks (Concerns, Assumptions, Blocking questions, Next step),
as text in your response.
