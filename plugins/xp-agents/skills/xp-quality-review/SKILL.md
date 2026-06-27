---
name: xp-quality-review
description: >-
  Independent review of the current diff. Spawns an xp-code-reviewer subagent
  that self-finds correctness (per-increment) or validates & fixes /code-review's
  findings (close path, MODE=consume-findings), plus drift, debt, and
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

> **Sequential discipline.** The harness batches independent tool calls in
> parallel; this skill is step-gated. Run Step 1 → 2 → 3 → 4 strictly, one
> step per turn — make the call, observe, then decide the next. Don't batch a
> step with the one that depends on it (e.g. acting on the xp-code-reviewer's
> findings before it returns); never spawn that reviewer subagent more than once
> **except** on the RISK=high escalation path (Step 1.5 below), where THREE
> angle-focused reviewer spawns issue in a SINGLE message as one step.
> Independent read-only calls may still batch.

Independent review of the current diff. The preload's `MODE` line selects Step 1's
correctness handling: **`MODE=self-find`** (per-increment, `/code-review` did NOT
run) — the xp-code-reviewer **self-finds correctness** itself; **`MODE=consume-findings`**
(close path, `/code-review` ran first) — Step 1 reads its JSON findings array and the
reviewer validates & fixes them. Both modes also cover quality/drift/debt.

## Step 1: Spawn Independent Code Reviewer

### Open concerns and debts the reviewer should see

The reviewer cannot infer which existing concerns or debts the diff might close; pass the relevant ones in the prompt so it can verify whether the staged changes address them and whether a `Resolves-Event:` trailer is warranted on the next commit. Pull candidates from the preload's `## Debt for Changed Files` section (open, unresolved debts/concerns whose files overlap the diff, via `commits.open_issues_matching_commit`) and from any plan-review concerns the preload lists. If the preload surfaced no overlapping events, state that explicitly — empty context reads as missing analysis, not absence.

### Gather Code-Review Findings (consume-findings mode only)

When `MODE=consume-findings`: read the JSON findings array `/code-review` returned (each entry: `file`, `line`, `summary`, `failure_scenario`); all are unaddressed. Pass them to the subagent to validate and fix. If the array is empty, say so in the prompt.

Format as a numbered list for the prompt — file, line, the finding summary, and its `failure_scenario`:
```
1. file.py:123 — "summary of the bug" (failure: <failure_scenario>)
2. other.py:45 — "summary of the bug" (failure: <failure_scenario>)
```

### Step 1.5: Risk-Gated Escalation (self-find only)

The preload's `## Risk Signal` block emits `RISK=high|low`. When `MODE=self-find`:

- **RISK=low** (default, most diffs) — single `xp-code-reviewer` spawn as below.
- **RISK=high** — spawn **THREE** `xp-code-reviewer` subagents **in parallel** (single message, three Agent tool calls) with distinct angle prompts. The diff/debt/SMM context blocks are identical across the three; only the `## Review Focus` block differs:
  - **[A] state-lifecycle**: "Focus on state field lifecycles: who sets each state field, who clears it, whether every set has a reachable clear on every path. Flag any latch/drain bug."
  - **[B] concurrency**: "Focus on concurrency and ordering: lock acquisition order, callback ordering, idempotency assumptions, race conditions between writers."
  - **[C] decision-path**: "Focus on decision/exit points: every `sys.exit`, `raise`, conditional return — confirm each branch is reachable, intentional, and not masking errors."

After all three return, **dedupe findings by (file, line, summary)** before acting on them. Cap total findings considered at 30. **Never escalate beyond 3 spawns** — that is the close-skill's `/code-review` job, gated at the close.

`MODE=consume-findings` (close path) is unaffected by RISK — the close already ran `/code-review` fan-out; the reviewer validates those findings.

### Build the Prompt and Spawn

Use the Agent tool to spawn the `xp-code-reviewer` subagent. The prompt must include everything the reviewer needs for an independent assessment — it has no conversation context. In `self-find` mode pass `## Code-Review Findings\nNone — self-find correctness` so the reviewer takes its self-find branch.

```
Agent(
  subagent_type: "xp-agents:xp-code-reviewer",
  prompt: "## Diff\n<diff from preload>\n\n## Code-Review Findings\n<numbered list, or 'None — self-find correctness'>\n\n## Existing Debt\n<debt from preload or 'None'>\n\n## SMM Directory\nSMM_DIR=<path>\n\nReview all four areas: correctness (validate handed-in findings, or self-find), drift, debt, reuse/quality/efficiency + XP values."
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

## Step 4: Report Back

Briefly summarize what was fixed, what was deferred as debt, and what was already clean. Do NOT append a status event — the PostToolUse hook records the lifecycle event.

## Guidelines

- **Independence is the point.** The xp-code-reviewer subagent has fresh context — it didn't write the code. Trust its judgment.
- **Courage over comfort.** If the subagent flags a finding as valid, default to applying the fix.
- **Run tests** after any changes to verify nothing breaks.
- If the subagent reports all code is clean, record the summary and move on.
