---
name: xp-stage-migration
description: >-
  Stage 2 floor migration prompt for /xp-kickoff. INTERNAL - invoked only by
  xp-kickoff when the stage is below 2.
allowed-tools:
  - Bash(python3 */smm/system_context_cli.py get-branching-field *)
  - Bash(python3 */smm/system_context_cli.py edit-branching-field *)
  - Bash(python3 */scripts/branching.py *stage)
  - Bash(python3 -c *datetime*)
  - Bash(printf *)
  - AskUserQuestion
---

# Stage 2 Floor Migration

> **Sequential discipline.** Run Step 1 → 2 → 3 one step per turn — never batch
> the `AskUserQuestion` with the `edit-branching-field` that records its answer.

## Step 1: Check dismissal

```bash
DISMISSED_AT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> \
  get-branching-field stage_prompt_dismissed_at)
```

If `DISMISSED_AT` is non-empty, log to the user (no prompt): *"Stage 2
migration prompt was dismissed
at {DISMISSED_AT}. To re-enable, run `printf null | python3
${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR>
edit-branching-field stage_prompt_dismissed_at`"*. Stop without further
steps.

## Step 2: Prompt

Prompt via `AskUserQuestion`, substituting the stage value: **"This project
is on branching Stage <N>. Stage 2 is the v3.1 plugin floor (sprint branches
required for production-grade discipline). Migrate to the Stage 2 floor now,
or continue at Stage <N> for this session?"**

## Step 3: Act on the choice

If the user picks **migrate**, write the Stage 2 floor directly
(`system_context.json` exists — kickoff Step 0 ran `/xp-system-context` first):
```bash
printf '2' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> \
  edit-branching-field stage
```
Do NOT record a dismissal. Return control to the caller (which re-reads stage
fresh, so do not cache).

If the user picks **continue**, record the dismissal:
```bash
TS=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())")
printf '%s' "\"$TS\"" | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> \
  edit-branching-field stage_prompt_dismissed_at
```
