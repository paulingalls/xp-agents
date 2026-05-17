---
name: xp-work-selection
description: >-
  This skill should be used when the user needs to select work for the session,
  review retro Try items, triage open questions, or pick sprint stories.
  Invoked as part of /xp-kickoff or standalone via /xp-work-selection.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Read
  - AskUserQuestion
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Work Selection

The session data above was preloaded automatically.

SMM_DIR=<path> is shown in the preload output. Use it for all append.sh calls.

Complete all applicable steps below in order. Skip steps where the preload shows no data.

## Step 1: Try Item Review (if Previous Try Items shown)

If the preload shows "### Previous Try Items", present them to the user.
Ask via AskUserQuestion for each: **adopt, defer, or drop?**

Pass the Try item text **verbatim, including any trailing `[refs: ...]`
suffix** — the helper extracts the refs and strips the suffix. Do NOT
craft `--metadata` JSON by hand.

**Adopt** (decision event with a slugged topic):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py adopt \
  --smm-dir <SMM_DIR> \
  --topic "retro-try-<2-3-word-slug>" \
  --content "<item text including any [refs: ...] suffix>"
```

Example topics: `retro-try-commit-after-green`, `retro-try-fix-gate-coverage`.
Never use bare `retro-try-adopted` — always include a descriptive slug.

**Defer** (status event, `disposition=deferred`):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py defer \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>"
```

**FORCE-CLOSE gate.** The defer command refuses with a non-zero exit
once the same Try has been deferred 3 times — carrying a Try across 3+
retros without adoption is dishonest. When the defer fails, present
the FORCE-CLOSE choice instead, picking exactly one of the three
escape flags below and re-running. The Try id named in the error tells
you which item is gated.

```bash
# Adopt: convert to a decision event with a slugged topic.
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py defer \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>" \
  --force-adopt "retro-try-<2-3-word-slug>"

# Drop: forget it; retro will never re-propose.
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py defer \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>" \
  --force-drop

# Defer with date: keep deferred, but record a target date in metadata.
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py defer \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>" \
  --force-defer-with-date YYYY-MM-DD
```

**Force-drop convention prompt (force-drop only).** BEFORE invoking
`--force-drop`, ask via AskUserQuestion: *"Record a durable convention
so retros never repropose this kind of Try?"* If yes, prompt for a
`retro-drop-<slug>` topic and rationale, then invoke `defer --force-drop`
ONCE with both flags below — emits drop + convention atomically. If no,
run `defer --force-drop` alone. Idempotent: re-drops with an existing
topic skip the convention and print a stderr notice with the discarded
rationale (the drop still fires). Regular `drop` does not offer this —
3+ retros is the courage moment that warrants the durable rule.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py defer \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>" \
  --force-drop \
  --record-convention-topic "retro-drop-<descriptive-slug>" \
  --record-convention-content "<one-sentence rationale>"
```

**Drop** (status event, `disposition=dropped` — retro agent will **never
re-propose** this Try):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py drop \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>"
```

## Step 2: Open Debts (if shown)

If the preload shows "### Open Debts:", present each item to the user via AskUserQuestion.
Options per item: **adopt-now**, **keep-deferred**, **drop**.

```bash
# adopt-now: resolve the debt, pull into current work
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py triage-adopt \
  --smm-dir <SMM_DIR> --event-id <event-id>

# keep-deferred: leave open for future triage
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py triage-defer \
  --smm-dir <SMM_DIR> --event-id <event-id>

# drop: resolve and forget
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py triage-drop \
  --smm-dir <SMM_DIR> --event-id <event-id>
```

## Step 3: Open Concerns (if shown)

If the preload shows "### Open Concerns:", process each item:

**Auto-resolve "MAYBE ADDRESSED" concerns:** If a concern is annotated with
"**MAYBE ADDRESSED** by: ..." and you judge the listed commits genuinely fix
the concern, auto-resolve it without asking the user:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py triage-drop \
  --smm-dir <SMM_DIR> --event-id <event-id>
```

**Present remaining concerns to user:** For concerns WITHOUT the "MAYBE
ADDRESSED" annotation, or where the overlapping commits don't clearly address
the concern, present via AskUserQuestion with options: adopt-now,
keep-deferred, drop. Same commands as Step 2.

## Step 4: Open Questions (if shown)

If the preload shows "### Open Questions:", present each item via AskUserQuestion.
Same options as Step 2 (adopt-now, keep-deferred, drop). Same commands with
the question's event-id.

## Step 5: Sprint / Work Selection (ALWAYS)

**If sprint active with ready stories:**
1. Show the ready stories from preload.
2. Ask via AskUserQuestion: "Which stories for this iteration?"
   Options: individual story IDs, "all ready stories", or "add ad-hoc story".
3. For ad-hoc stories: ask for title and brief description, then add via CLI:
   ```bash
   echo '{"id":"story-NNN","title":"...","status":"scheduled","dependencies":[],"acceptance_criteria":["..."]}' \
     | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> add-story
   ```
4. For selected stories: mark each as `scheduled` (queued for this
   iteration). xp-assign promotes the first scheduled story to
   `in-progress` when it creates the branch.
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
     update-story story-NNN scheduled
   ```
5. Record status event:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
     --type "status" --agent "xp-work-selection" \
     --content "Story selection: marked N stories scheduled" \
     --working-on '[]'
   ```

**If sprint active but no ready stories (all scheduled, in-progress, or done):**
Report "All stories are queued, in progress, or complete. Continuing."

**If no active sprint:**
Ask the user "What should we work on this session?" via AskUserQuestion.
Record their response as a goal event:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "goal" --agent "xp-work-selection" \
  --content "<user's goal>"
```

## If Nothing Needs Doing

If no Try items, no questions, and no sprint with ready stories, report
briefly and complete. Do not force the user through unnecessary interaction.
