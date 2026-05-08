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
  - Bash(python3 */smm/smm_cli.py *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# End Session

User-invoked. The preload above provides:
- `SMM_DIR=<path>` — pass to every append.sh call.
- `### CANDIDATES` — mechanical line-per-event narrative draft (newest at the bottom; an `...` prefix means older lines were trimmed to fit budget).
- `### OPEN_QUESTIONS` — event ids of questions still open in this session.
- `### LIKELY_ADDRESSED` — concern/debt event ids whose files overlap a recent commit, each followed by indented git commit hash(es) for the audit trail (resolvable via `git show`).
- `### UNCOMMITTED` — count of SMM events newer than the last commit event.

Run all five steps in order. Do **not** prompt the user before Step 1 — the design is friction-free; the user invoked `/xp-end-session` because they want this work done.

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

## Step 3: Auto-judge likely-addressed concerns and debts

The preload's `### LIKELY_ADDRESSED` section lists each concern/debt
ID followed by indented git commit hash(es) whose files overlap. **Judge
each item yourself — do not prompt the user.** For each grouping:

- **Auto-resolve** when the cited commits clearly fix the concern's
  intent. All three must hold:
  - commit message wording matches the concern's stated problem,
  - the concern's `files` are the obvious target of the change,
  - no remaining work is implied (no "TODO", "follow-up", or scope
    deferral in the commit body).
  When multiple commits are cited, ALL must contribute to the fix —
  if any cited commit is unrelated or only partially addresses the
  concern, defer instead. Append a status event citing both the
  canonical resolution link AND the git commit hash(es) that informed your
  judgement:

  ```bash
  ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
    --type status --agent xp-end-session \
    --content "Resolved by <commit_hash>: <one-line rationale>" \
    --working-on '[]' \
    --metadata '{"action":"end_session_drop","resolves":["<concern_id>"],"resolved_by_commits":["<commit_hash>"]}'
  ```

- **Defer** when the file overlap is incidental, intent isn't
  clearly fulfilled, or you can't confidently judge from available
  context. Append nothing — the concern stays open and re-surfaces
  at next kickoff (same effective behavior as if the user never ran
  this skill on that item). The default is to defer when in doubt.

**Where to find commit content:**
- The cited values are real git commit hashes — `git show <hash>`
  reads the full message + diff regardless of author (works for both
  solo commits and teammate worktree subagent commits).
- For commits you authored this session (solo work), the message may
  also be in your conversation history.

After processing all items, print a one-line summary to the user:
> "Auto-resolved N items: <ids>. Deferred M items: <ids> — <one-line reason>."

The `action: "end_session_drop"` lets retro tooling distinguish
end-of-session auto-judges from organic concern/debt resolutions;
`resolved_by_commits` carries the audit trail of which git commit
hash(es) informed each decision.

## Step 4: Persist into session_history.json

Pipe the draft_summary helper's JSON output into write_history.py. The CLI reads stdin, builds a `{ts, summary, carry_forward}` entry, appends it to `session_history.json` (ring-buffer beside `events.jsonl` in `SMM_DIR`), then prunes any carry_forward items whose referenced events are already resolved in the current event log.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/draft_summary.py --smm-dir <SMM_DIR> \
  | python3 ${CLAUDE_SKILL_DIR}/scripts/write_history.py --smm-dir <SMM_DIR>
```

`session_history.json` schema is `{version: 1, entries: [{ts, summary, carry_forward[]}]}`. Retention is **N=5** entries — appending the 6th evicts the oldest. A future kickoff step will render the most recent entry as "Last session at a glance"; long-term truth lives in the SMM Wisdom/Risks pillars, not here.

Run this AFTER Step 1 so the session_summary event Step 1 just appended is included when `draft_summary.py` re-scans `events.jsonl` here. The persisted summary comes from `draft_summary.run()` (fresh line-per-event scan), not from the agent-refined narrative in Step 1's event — the two are intentionally distinct: the event captures the final narrative, the history entry captures the mechanical scan. The pipe exits non-zero if the draft is malformed JSON or if the existing history file is corrupt — surface the error and stop rather than silently moving on.

## Step 5: Honesty signal

Surface the `### UNCOMMITTED` value to the user verbatim. If `> 0`, suggest they commit before ending the session — the next session's resolves-trailer probe relies on commit-linked events for accurate suggestions.

Example output:
> "Uncommitted SMM events since last commit: **N**. Consider committing before ending so the next session's probe has fresh data."

If `N == 0`, no nag needed; report briefly and stop.
