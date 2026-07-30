---
name: xp-work-selection
description: >-
  Select work for the session: review retro Try items, triage open questions
  and debts, pick sprint stories.
allowed-tools:
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(*/skills/*/scripts/*)
  - Read
  - AskUserQuestion
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Work Selection

> **Sequential discipline.** Run Step 1 → 2 → 3 → 4 → 5 strictly, one step per
> turn — make the call, observe, then decide the next. Never batch an
> `AskUserQuestion` with the action consuming its answer (a Try/triage question
> vs the decide/triage append that records it).

Use the preload's `SMM_DIR=<path>` for all append.sh calls. Complete all applicable steps in order; skip steps where the preload shows no data.

## Step 1: Try Item Review (if Previous Try Items shown)

If the preload shows "### Previous Try Items", present them and ask via
AskUserQuestion for each: **adopt, defer, or drop?**

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
Never a bare `retro-try-adopted`.

**Defer** (status event, `disposition=deferred`):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py defer \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>"
```

**FORCE-CLOSE gate.** The defer command refuses with a non-zero exit
once the same Try has been deferred 3 times — carrying a Try across 3+
retros without adoption is dishonest. When the defer fails, present the
FORCE-CLOSE choice and re-run with exactly one of the three escape
flags below; the error names the gated Try id.

```bash
# Append exactly ONE escape flag:
#   --force-adopt "retro-try-<2-3-word-slug>"  convert to a decision event
#   --force-drop                               forget it
#   --force-defer-with-date YYYY-MM-DD         stay deferred, record a target date
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py defer \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>" \
  <escape flag>
```

**Force-drop convention prompt (force-drop only).** BEFORE invoking
`--force-drop`, ask via AskUserQuestion: *"Record a durable convention
so retros never repropose this kind of Try?"* If yes, prompt for a
`retro-drop-<slug>` topic and rationale, then invoke `defer --force-drop`
ONCE with both flags below — emits drop + convention atomically. If no,
run `defer --force-drop` alone. Idempotent: re-drops with an existing
topic skip the convention and print a stderr notice with the discarded
rationale (the drop still fires). Regular `drop` does not offer this —
3+ retros is the courage moment that warrants a durable rule.

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

If the preload shows "### Open Debts:", present each item via AskUserQuestion.
Options per item: **adopt-now**, **keep-deferred**, **drop**.

Adopting takes the work ON; it does NOT close the item, which stays open
until the fix actually lands (a commit with a `Resolves-Event:` trailer
closes it). Only a drop is terminal.

**Relay the intent suffix.** An already-triaged item carries
`— ADOPTED (<age>, by <id>)` or `— DEFERRED x<N>`. Present it **verbatim**
with the item: it is the memory that the user already said yes to this, or
already put it off N times. The item is listed because it is still OPEN, not
because the earlier decision was forgotten — do not re-offer it as if it were
new. An item ADOPTED several sessions ago that still has not landed is worth
saying so out loud; one DEFERRED 3+ times is worth dropping or doing.

```bash
# adopt-now: pull into current work
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py triage-adopt \
  --smm-dir <SMM_DIR> --event-id <event-id>

# keep-deferred: leave open for future triage
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py triage-defer \
  --smm-dir <SMM_DIR> --event-id <event-id>

# drop: close and forget — never raised again
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py triage-drop \
  --smm-dir <SMM_DIR> --event-id <event-id>
```

## Step 3: Open Concerns (if shown)

If the preload shows "### Open Concerns:", process each item:

**Auto-resolve "MAYBE ADDRESSED" concerns:** If a concern is annotated with
"**MAYBE ADDRESSED** by: ..." and you judge the listed commits genuinely fix
it, auto-resolve without asking the user. A "#### Deferred earlier" line is an
index excerpt, not the whole concern — `get-event` it (command in that header)
before dropping; a drop is terminal:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py triage-drop \
  --smm-dir <SMM_DIR> --event-id <event-id>
```

**Present remaining concerns to user:** For concerns WITHOUT the "MAYBE
ADDRESSED" annotation, or where the overlapping commits don't clearly address
it, present via AskUserQuestion with options: adopt-now, keep-deferred, drop.
Same commands as Step 2.

## Step 4: Open Questions (if shown)

If the preload shows "### Open Questions:", present each item via AskUserQuestion.
Same options and commands as Step 2, with the question's event-id.

## Step 5: Sprint Story Selection (if sprint active)

**If sprint active with ready stories:**
1. Show the ready stories from preload.
2. Ask via AskUserQuestion: "Which stories for this iteration?"
   Options: individual story IDs, "all ready stories", or "add ad-hoc story".
3. For ad-hoc stories: ask for title and brief description, then add via CLI:
   ```bash
   echo '{"id":"story-NNN","title":"...","status":"scheduled","dependencies":[],"acceptance_criteria":["..."]}' \
     | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> add-story
   ```
4. For selected stories: mark each `scheduled`. /xp-schedule promotes the
   ready frontier to `in-progress` and sets each `execution_mode`.
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

## If Nothing Needs Doing

If no Try items, no questions, and no sprint with ready stories, report
briefly and complete — do not manufacture interaction.
