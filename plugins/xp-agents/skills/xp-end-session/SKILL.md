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
- `### UNCOMMITTED` — count of concerns/debts/discoveries newer than the last commit event.

Run all five steps in order. Do **not** prompt the user before Step 1 — the user invoked `/xp-end-session` because they want this work done.

## Step 1: Append the session_summary event

Write a 1–2 paragraph narrative summary of the current session (≤2000 chars — the schema budget). Keep verbs in past tense, name what shipped and what's open. Use the `### CANDIDATES` text to trigger your memory. Append using:

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
4. If the user picks **drop** (won't fix):
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/smm/smm_cli.py --smm-dir <SMM_DIR> \
     question close --won-fix --event-id <question_id> --rationale "<one-line reason>"
   ```

## Step 3: Auto-judge likely-addressed concerns and debts

The preload's `### LIKELY_ADDRESSED` section lists each concern/debt
ID followed by indented git commit hash(es) whose files overlap. **Judge
each item yourself — do not prompt the user.** Inspect any cited commit
via `git show <hash>` (works for both solo and teammate worktree commits).
For each grouping:

- **Auto-resolve** when the cited commits clearly fix the concern's intent. All three must hold:
  - commit message wording matches the concern's stated problem,
  - the concern's `files` are the obvious target of the change,
  - no remaining work is implied (no "TODO", "follow-up", or scope deferral in the commit body).
Append a status event citing both the canonical resolution link AND the git commit hash(es) that informed your judgement:

  ```bash
  ${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
    --type status --agent xp-end-session \
    --content "Resolved by <commit_hash>: <one-line rationale>" \
    --working-on '[]' \
    --metadata '{"action":"end_session_drop","resolves":["<concern_id>"],"resolved_by_commits":["<commit_hash>"]}'
  ```

  `action` distinguishes auto-judges from organic resolutions; `resolved_by_commits` is the audit trail.

- **Defer** when the file overlap is incidental, intent isn't
  clearly fulfilled, or you can't confidently judge from available
  context. Append nothing — the concern stays open and re-surfaces
  at next kickoff. Default to defer when in doubt.

After processing all items, print a one-line summary to the user:
> "Auto-resolved N items: <ids>. Deferred M items: <ids> — <one-line reason>."

## Step 4: Persist into session_history.json

Run AFTER Step 1 so the just-appended session_summary event is included in the re-scan:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/draft_summary.py --smm-dir <SMM_DIR> \
  | python3 ${CLAUDE_SKILL_DIR}/scripts/write_history.py --smm-dir <SMM_DIR>
```

Retention is **N=5** entries — appending the 6th evicts the oldest. The pipe exits non-zero if the draft is malformed JSON or the existing history file is corrupt — surface the error and stop.

## Step 5: Honesty signal

Surface the `### UNCOMMITTED` value to the user verbatim. The count is concerns/debts/discoveries newer than the last commit event — items the next session's resolves-trailer probe will see as open candidates.

If `> 0`, suggest one of:
- **Drop now** if the items are addressed conceptually but not formally resolved — append a status event with `metadata.resolves: [<id>]` (mirrors Step 3's auto-judge pattern).
- **Leave for triage** — they re-surface at the next kickoff's `/xp-work-selection` and can be dropped, deferred, or adopted then.

Example output:
> "Open SMM items newer than last commit: **N** (concerns/debts/discoveries). Drop now if addressed, or let next kickoff triage them."

If `N == 0`, no nag needed; report briefly and stop.
