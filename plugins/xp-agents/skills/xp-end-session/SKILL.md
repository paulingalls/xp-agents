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

For each id in `### OPEN_QUESTIONS`:

1. Use `AskUserQuestion` with options: **answer / defer / drop**.
2. If the user picks **answer**, follow up with a second `AskUserQuestion` to capture the free-text answer (or use the `Other` field). Then:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
     --type answer --agent xp-end-session \
     --references '["<question_id>"]' \
     --content "<user's answer>"
   ```
3. If the user picks **defer**, leave the question open — no event. It surfaces at next kickoff.
4. If the user picks **drop** (won't fix), use the canonical CLI helper. It stamps the structured `Closed question {id[:8]} as won't-fix:` content prefix and is idempotent for already-resolved questions:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py --smm-dir <SMM_DIR> \
     question close --won-fix --event-id <question_id> --rationale "<one-line reason>"
   ```

## Step 3: Drop likely-addressed concerns and debts

For each id in `### LIKELY_ADDRESSED`, append a status event resolving it. The preload already filtered to items whose files overlap a recent commit, so the default action is "drop" — but ask the user once for the whole batch (`Drop these N items?`) before bulk-appending. If the user disagrees on specific items, skip them and leave open.

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type status --agent xp-end-session \
  --content "Resolved by recent commit: <brief>" \
  --working-on '[]' \
  --metadata '{"action":"end_session_drop","resolves":["<concern_or_debt_id>"]}'
```

The `action: "end_session_drop"` lets retro tooling distinguish bulk
end-of-session drops from organic concern/debt resolutions.

## Step 4: Honesty signal

Surface the `### UNCOMMITTED` value to the user verbatim. If `> 0`, suggest they commit before ending the session — the next session's resolves-trailer probe relies on commit-linked events for accurate suggestions.

Example output:
> "Uncommitted SMM events since last commit: **N**. Consider committing before ending so the next session's probe has fresh data."

If `N == 0`, no nag needed; report briefly and stop.
