---
name: xp-quality-review
description: >-
  Post-code-review quality review. Spawns an independent xp-code-reviewer subagent
  to validate and fix /code-review's findings, plus drift, debt, and
  reuse/quality/efficiency + XP-lens review. Resolves plan concerns inline.
effort: high
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Agent
  - Skill
  - Bash(*/skills/*/scripts/*)
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(python3 -m unittest *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Quality Review

Post-code-review review. `/code-review` just ran — an identify-only correctness pass that returns a JSON array of findings (it fixes nothing). You orchestrate an independent review and resolve plan concerns.

## Step 1: Spawn Independent Code Reviewer

### Open concerns and debts the reviewer should see

The reviewer cannot infer which existing concerns or debts the diff might close; pass the relevant ones in the prompt so it can verify whether the staged changes address them and whether a `Resolves-Event:` trailer is warranted on the next commit. Pull candidates from the preload's `## Debt for Changed Files` section (already filtered by file overlap via `concerns.find_issues_for_file`) and from any plan-review concerns the preload lists. If the preload surfaced no overlapping events, state that explicitly — empty context reads as missing analysis, not absence.

### Gather Code-Review Findings

Read the JSON findings array `/code-review` returned (each entry: `file`, `line`, `summary`, `failure_scenario`); all are unaddressed. Pass them to the subagent to validate and fix. If the array is empty, say so in the prompt.

Format as a numbered list for the prompt — file, line, the finding summary, and its `failure_scenario`:
```
1. file.py:123 — "summary of the bug" (failure: <failure_scenario>)
2. other.py:45 — "summary of the bug" (failure: <failure_scenario>)
```

### Build the Prompt and Spawn

Use the Agent tool to spawn the `xp-code-reviewer` subagent. The prompt must include everything the reviewer needs for an independent assessment — it has no conversation context:

```
Agent(
  subagent_type: "xp-agents:xp-code-reviewer",
  prompt: "## Diff\n<diff from preload>\n\n## Code-Review Findings\n<numbered list>\n\n## Existing Debt\n<debt from preload or 'None'>\n\n## SMM Directory\nSMM_DIR=<path>\n\nReview all four areas: validate & fix the findings, drift, debt, reuse/quality/efficiency + XP values."
)
```

Wait for the subagent to complete. Its findings and any recorded events will be returned as a tool result.

## Step 2: Resolve Plan Review Concerns

The preload lists open concerns from the plan reviewer. For each concern:

- **If code changes address it** — resolve it:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-quality-review" \
  --content "Resolved: [what was addressed]" \
  --working-on '[]' --metadata '{"resolves": ["<concern-event-id>"]}'
```

- **If the concern is still open** — leave it.

If no open plan concerns are listed in the preload, skip this step.

## Step 3: Act on Subagent Findings

Review the xp-code-reviewer's summary. For each finding:

- **Fix directly** (preferred — courage). Edit files to address the issue. Run tests afterward.
- **Fix overlapping open concerns now (COURAGE-FIX).** If an open plan-review or close-reviewer concern's `files` overlap the diff you're already touching, fix it now while the file is open — file overlap is in scope, no re-litigation. Don't defer to "MAYBE ADDRESSED" triage at close time. Resolve via the `Resolves-Event:` trailer in the same commit.
- **Already recorded** by subagent via append.sh — no further action needed.
- **Record as debt** if fix is too large for this review:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "debt" --agent "xp-quality-review" \
  --content "What needs fixing and why" --files '["path/to/file.py"]'
```

## Step 4: Re-review the Staged Diff Before Commit

If any files changed during Steps 2-3, stage them and re-run `/code-review` on the staged diff **once**. Fix any correctness findings it surfaces, then commit. Do not loop: if a finding can't be fixed in this pass, record it as debt and commit. If nothing changed, commit directly.

## Step 5: Report Back

Briefly summarize what was fixed, what was deferred as debt, and what was already clean. Do NOT append a status event — the PostToolUse hook records the lifecycle event.

## Guidelines

- **Independence is the point.** The xp-code-reviewer subagent has fresh context — it didn't write the code. Trust its judgment.
- **Courage over comfort.** If the subagent flags a finding as valid, default to applying the fix.
- **Run tests** after any changes to verify nothing breaks.
- If the subagent reports all code is clean, record the summary and move on.
