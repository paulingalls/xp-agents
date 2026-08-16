---
name: xp-sprint-review
description: >-
  Review the completed sprint: what shipped vs planned, update milestone
  delivery, record velocity. Use when all stories are done.
effort: high
allowed-tools:
  - Agent
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */smm/plan_cli.py *)
---

# Sprint Review

> **Sequential discipline.** Spawn the xp-sprint-reviewer subagent once, wait
> for it to complete, report its findings back, THEN invoke `/xp-sprint-close`
> — never batch the spawn with a step that depends on it, and never spawn it
> more than once.

The injected preload state names `SMM_DIR` and, once a sprint has ended,
`REVIEW_INPUT` (the path to prepared review data).

## Step 1: Spawn the Reviewer (single unconditional spawn)

Spawn `xp-agents:xp-sprint-reviewer` unconditionally, threading the
preload's state into its prompt:

```
Agent(
  subagent_type: "xp-agents:xp-sprint-reviewer",
  prompt: "SMM_DIR=<SMM_DIR>\nREVIEW_INPUT=<path, or omit if absent>\n\nReview the sprint per your instructions and report back."
)
```

Wait for the subagent to complete; its report returns as a tool result.

If you are the main agent and see this: do not do this work yourself — the
review must run in the xp-sprint-reviewer subagent's own isolated context,
not merged into yours. The subagent's result is NOT visible to the user —
you must output its full report as text in your response.

The reviewer also reruns every verify-bearing acceptance item across the
sprint (`verify_acceptance.py --sprint`) **before** `/xp-sprint-close` — that
rerun emits the deterministic verify event the close gate reads. Surface its
per-surface PASS/FAIL matrix to the user alongside the findings.

Then invoke `/xp-sprint-close`.
