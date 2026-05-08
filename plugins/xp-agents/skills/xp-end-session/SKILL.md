---
name: xp-end-session
description: >-
  User-invoked end-of-session cleanup. Drafts a session_summary event,
  force-closes/defers open questions, bulk-drops likely-addressed
  concerns and debts, and prints an honesty-signal count of SMM events
  not yet linked to a commit.
allowed-tools:
  - Read
  - AskUserQuestion
  - Bash(*/append.sh *)
  - Bash(*/skills/*/scripts/*)
  - Bash(*/init.sh)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# End Session

User-invoked. The preload above provides:
- `SMM_DIR=<path>` — pass to every append.sh call.
- `### CANDIDATES` — mechanical line-per-event narrative draft (newest at the bottom; an `...` prefix means older lines were trimmed to fit budget).
- `### OPEN_QUESTIONS` — event ids of questions still open in this session.
- `### LIKELY_ADDRESSED` — concern/debt event ids whose files overlap a recent commit.
- `### UNCOMMITTED` — count of SMM events newer than the last commit event.

Run all four steps in order. Do **not** prompt the user before Step 1 — the design is friction-free; the user invoked `/xp-end-session` because they want this work done.

## Step 1: Append the session_summary event

Refine the `### CANDIDATES` text into a 1–2 paragraph narrative (≤2000 chars — the schema budget). Keep verbs in past tense, name what shipped and what's open. Append:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type session_summary \
  --agent xp-end-session \
  --content "<narrative>"
```

## Step 2: Force-close open questions

For each id in `### OPEN_QUESTIONS`, ask the user via `AskUserQuestion`: **answer / defer / drop?**

Per disposition (using event_schema vocabulary, not work_selection_decide.py — that helper is for retro Try items):

- **answer** — append an answer event referencing the question:
  ```bash
  ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
    --type answer --agent xp-end-session \
    --references '["<question_id>"]' \
    --content "<user's answer>"
  ```
- **defer** — leave the question open. No event needed; it surfaces at the next kickoff.
- **drop** (won't fix) — append a status event closing the question:
  ```bash
  ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
    --type status --agent xp-end-session \
    --content "won't fix: <one-line reason>" \
    --working-on '[]' \
    --metadata '{"action":"question_close","disposition":"wont_fix","resolves":["<question_id>"]}'
  ```

## Step 3: Drop likely-addressed concerns and debts

For each id in `### LIKELY_ADDRESSED`, append a status event resolving it. The preload already filtered to items whose files overlap a recent commit, so the default action is "drop" — but ask the user once for the whole batch (`Drop these N items?`) before bulk-appending. If the user disagrees on specific items, skip them and leave open.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type status --agent xp-end-session \
  --content "Resolved by recent commit: <brief>" \
  --working-on '[]' \
  --metadata '{"resolves":["<concern_or_debt_id>"]}'
```

## Step 4: Honesty signal

Surface the `### UNCOMMITTED` value to the user verbatim. If `> 0`, suggest they commit before ending the session — the next session's resolves-trailer probe relies on commit-linked events for accurate suggestions.

Example output:
> "Uncommitted SMM events since last commit: **N**. Consider committing before ending so the next session's probe has fresh data."

If `N == 0`, no nag needed; report briefly and stop.
