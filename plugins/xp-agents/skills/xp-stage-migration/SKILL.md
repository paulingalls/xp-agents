---
name: xp-stage-migration
description: >-
  Stage 2 floor migration prompt for /xp-kickoff Step 2.4. Reads dismissal,
  prompts customer to migrate via /xp-sprint-start or records a dismissal.
  INTERNAL — invoked only by xp-kickoff when stage < 2.
allowed-tools:
  - Bash(python3 */smm/system_context_cli.py get-branching-field *)
  - Bash(python3 */smm/system_context_cli.py edit-branching-field *)
  - Bash(python3 */scripts/branching.py *stage)
  - Bash(python3 -c *datetime*)
  - Bash(printf *)
  - AskUserQuestion
  - Skill
---

# Stage 2 Floor Migration

## Step 1: Check dismissal

```bash
DISMISSED_AT=$(python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> \
  get-branching-field stage_prompt_dismissed_at)
```

If `DISMISSED_AT` is non-empty, the user has already declined the migration
once. Log to the user (no prompt): *"Stage 2 migration prompt was dismissed
at {DISMISSED_AT}. To re-enable, run `printf null | python3
${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR>
edit-branching-field stage_prompt_dismissed_at`"*. Stop without further
steps.

## Step 2: Prompt

Prompt via `AskUserQuestion`, substituting the stage value: **"This project
is on branching Stage <N>. Stage 2 is the v3.1 plugin floor (sprint branches
required for production-grade discipline). Migrate now via /xp-sprint-start,
or continue at Stage <N> for this session?"**

## Step 3: Act on the choice

If the user picks **migrate**, invoke `/xp-sprint-start`. Do NOT record
a dismissal — migration is the non-dismissed branch. After it completes,
return control to the caller (which re-reads stage fresh, so do not
cache).

If the user picks **continue**, record the dismissal:
```bash
TS=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())")
printf '%s' "\"$TS\"" | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> \
  edit-branching-field stage_prompt_dismissed_at
```
