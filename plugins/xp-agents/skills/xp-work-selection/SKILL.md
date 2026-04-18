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
suffix** — the helper extracts the refs, wires `metadata.resolves`, and
strips the suffix from the stored content. Do NOT craft `--metadata` JSON
by hand.

**Adopt** (decision event with a slugged topic):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py adopt \
  --smm-dir <SMM_DIR> \
  --topic "retro-try-<2-3-word-slug>" \
  --content "<item text including any [refs: ...] suffix>"
```

Example topic: `retro-try-commit-after-green`, `retro-try-fix-gate-coverage`.
Never use bare `retro-try-adopted` — always include a descriptive slug.

**Defer** (status event, `disposition=deferred`):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py defer \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>"
```

**Drop** (status event, `disposition=dropped` — retro agent will **never
re-propose** this Try):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-work-selection/scripts/work_selection_decide.py drop \
  --smm-dir <SMM_DIR> \
  --content "<item text including any [refs: ...] suffix>"
```

## Step 2: Open Questions (if shown)

If the preload shows "### Open Questions", present blocking or high-priority
items to the user. Ask via AskUserQuestion for resolution.

Record answers:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "answer" --agent "xp-work-selection" \
  --content "Answer: <user response>" \
  --references '["<question-event-id>"]'
```

If the user declines to answer, move on gracefully.

## Step 3: Sprint / Work Selection (ALWAYS)

**If sprint active with ready stories:**
1. Show the ready stories from preload.
2. Ask via AskUserQuestion: "Which stories for this iteration?"
   Options: individual story IDs, "all ready stories", or "add ad-hoc story".
3. For ad-hoc stories: ask for title and brief description, then add via CLI:
   ```bash
   echo '{"id":"story-NNN","title":"...","status":"in-progress","size":"M","dependencies":[],"acceptance_criteria":["..."]}' \
     | python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> add-story
   ```
4. For selected stories: update each story's status via CLI:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir <SMM_DIR> \
     update-story story-NNN in-progress
   ```
5. Record status event:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
     --type "status" --agent "xp-work-selection" \
     --content "Story selection: marked N stories in-progress" \
     --working-on '[]'
   ```

**If sprint active but no ready stories (all in-progress or done):**
Report "All stories are in progress or complete. Continuing."

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
