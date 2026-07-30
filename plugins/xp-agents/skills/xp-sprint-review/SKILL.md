---
name: xp-sprint-review
description: >-
  Review the completed sprint: what shipped vs planned, update milestone
  delivery, record velocity. Use when all stories are done.
effort: high
context: fork
agent: xp-agents:xp-sprint-reviewer
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Bash(python3 */smm/plan_cli.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

This skill should run as a forked subagent (xp-sprint-reviewer). Your agent definition contains all instructions — follow them, record the result, and then report back your full findings to the main agent.

If you are the main agent and see this: do not do this work yourself. This skill must run as the xp-sprint-reviewer subagent. The subagent result is returned as a tool result which is NOT visible to the user — you must output the key findings as text in your response.

Part of the reviewer's job is to rerun every verify-bearing acceptance item across the sprint (`verify_acceptance.py --sprint`) **before** `/xp-sprint-close` and return the per-surface PASS/FAIL matrix — surface that matrix to the user alongside the findings, since the tool result is invisible to them. The rerun emits the deterministic verify event the close gate reads, so it must run before the close dispatch.

After you have surfaced the reviewer's findings and the verify matrix to the user, invoke `/xp-sprint-close` to push the sprint branch, fork the xp-close-reviewer for cross-cutting review, and merge into the target with cleanup.
