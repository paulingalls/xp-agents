---
name: xp-quality-review
description: >-
  Independent review of the diff. Spawns xp-code-reviewer for correctness,
  drift, debt, reuse/quality, prose hygiene.
effort: high
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Agent
  - Skill
  - Bash
  - Bash(*/skills/*/scripts/*)
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
---

# Quality Review

> **Sequential discipline.** Run Step 1 → 2 → 3 → 4 → 5 one per turn: make the
> call, observe, then decide the next. Never batch a step with one that depends
> on it, and never spawn the reviewer subagent more than once; independent
> read-only calls may batch.

The preload's `MODE` line selects Step 1's correctness handling:
**`MODE=self-find`** (per-increment, `/code-review` did NOT run) — the
xp-code-reviewer **self-finds correctness** itself; **`MODE=consume-findings`**
(close path, `/code-review` ran first) — Step 1 reads its JSON findings array
and the reviewer validates & fixes them. Both modes also cover quality/drift/debt.

## Step 1: Gather Reviewer Inputs

### Open concerns and debts the reviewer should see

Pass the relevant existing concerns and debts in the prompt — the reviewer cannot infer which ones the diff might close, and it must judge whether the changes address them and whether a `Resolves-Event:` trailer is warranted on the next commit. Pull candidates from the preload's `## Debt for Changed Files` section (open, unresolved debts/concerns whose files overlap the diff) and from any plan-review concerns the preload lists. If the preload surfaced no overlapping events, state that explicitly — empty context reads as missing analysis, not absence.

### Gather Code-Review Findings (consume-findings mode only)

When `MODE=consume-findings`: `/code-review` runs via the Workflow tool, so its verified findings arrive in the **task-notification result** (a `findings` array; each entry: `file`, `line`, `summary`, `failure_scenario`) — read them from there, not from a Skill result. All are unaddressed; pass them to the subagent to validate and fix. If the array is empty, say so in the prompt.

Format as a numbered list for the prompt:
```
1. file.py:123 — "summary of the bug" (failure: <failure_scenario>)
2. other.py:45 — "summary of the bug" (failure: <failure_scenario>)
```

## Step 2: Build Reviewer Prompt and Spawn (single unconditional spawn)

Build the `xp-code-reviewer` prompt now and spawn the reviewer **unconditionally**. In `self-find` mode pass `## Code-Review Findings\nNone — self-find correctness` so the reviewer takes its self-find branch — it self-triages the diff's risk from the change itself and its injected Constraints pillar (Section 1c) and elevates the risky angles on its own. In `consume-findings` mode pass the numbered findings list from Step 1. When a close cycle id is in scope for this invocation (a close skill supplied one), add a `## Close Cycle ID\n<value>` section to the prompt; absent a close cycle id (per-commit review), omit the section entirely.

**Single-spawn invariant.** Exactly ONE `xp-code-reviewer` spawn per cycle. Do NOT fan-out into multiple parallel spawns — sprint-103's 3-spawn fan-out had irreducible coordination races (filesystem writes, SMM appends, dedupe-key fragility).

```
Agent(
  subagent_type: "xp-agents:xp-code-reviewer",
  prompt: "## Diff\n<diff>\n\n## Code-Review Findings\n<numbered list, or 'None — self-find correctness'>\n\n## Existing Debt\n<debt>\n\n## SMM Directory\nSMM_DIR=<path>\n\nReview all five areas: correctness, drift, debt, reuse/quality/efficiency + XP values, prose hygiene."
)
```

Wait for the subagent to complete; its findings and recorded events return as a tool result.

## Step 3: Resolve Plan Review Concerns

The preload lists open concerns from the plan reviewer. For each concern:

- **If code changes address it** — resolve it:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-quality-review" \
  --content "Resolved: [what was addressed]" \
  --working-on '[]' --metadata '{"resolves": ["<concern-event-id>"]}'
```

- **If the concern is still open** — leave it.

No open plan concerns in the preload → skip this step.

## Step 4: Act on Subagent Findings

Review the xp-code-reviewer's summary. For each finding:

- **Fix directly** (preferred — courage). Edit files to address the issue, then re-run the preload's `TEST_COMMAND`.
- **Fix overlapping open concerns now (COURAGE-FIX).** If an open plan-review or close-reviewer concern's `files` overlap the diff you're already touching, fix it now while the file is open — file overlap is in scope, no re-litigation. Don't defer to "MAYBE ADDRESSED" triage at close time. Resolve via the `Resolves-Event:` trailer in the same commit.
- **Already recorded** by subagent via append.sh — no further action needed.
- **Record as debt** if fix is too large for this review:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "debt" --agent "xp-quality-review" \
  --content "What needs fixing and why" --files '["path/to/file.py"]'
```

## Step 5: Report Back

Briefly summarize what was fixed, what was deferred as debt, and what was already clean. Do NOT append a status event — the PostToolUse hook records the lifecycle event.

## Guidelines

- **Independence is the point.** The xp-code-reviewer subagent has fresh context — it didn't write the code. Trust its judgment: if it flags a finding as valid, default to applying the fix.
- **Run the preload's `TEST_COMMAND`** after any changes to verify nothing breaks. If it is empty this project declared none — say so rather than guessing a runner, and give the customer the setter verbatim: `printf %s '"<your-test-command>"' | python3 ${CLAUDE_PLUGIN_ROOT}/smm/system_context_cli.py --smm-dir <SMM_DIR> edit-stack-field test_command`.
- If the subagent reports all code is clean, record the summary and move on.
