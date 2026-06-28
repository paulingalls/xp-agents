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
> findings before it returns); never spawn that reviewer subagent more than once.
> Independent read-only calls may still batch.

Independent review of the current diff. The preload's `MODE` line selects Step 1's
correctness handling: **`MODE=self-find`** (per-increment, `/code-review` did NOT
run) — the xp-code-reviewer **self-finds correctness** itself; **`MODE=consume-findings`**
(close path, `/code-review` ran first) — Step 1 reads its JSON findings array and the
reviewer validates & fixes them. Both modes also cover quality/drift/debt.

## Step 1: Gather Reviewer Inputs

### Open concerns and debts the reviewer should see

The reviewer cannot infer which existing concerns or debts the diff might close; pass the relevant ones in the prompt so it can verify whether the staged changes address them and whether a `Resolves-Event:` trailer is warranted on the next commit. Pull candidates from the preload's `## Debt for Changed Files` section (open, unresolved debts/concerns whose files overlap the diff, via `commits.open_issues_matching_commit`) and from any plan-review concerns the preload lists. If the preload surfaced no overlapping events, state that explicitly — empty context reads as missing analysis, not absence.

### Gather Code-Review Findings (consume-findings mode only)

When `MODE=consume-findings`: read the JSON findings array `/code-review` returned (each entry: `file`, `line`, `summary`, `failure_scenario`); all are unaddressed. Pass them to the subagent to validate and fix. If the array is empty, say so in the prompt.

Format as a numbered list for the prompt — file, line, the finding summary, and its `failure_scenario`:
```
1. file.py:123 — "summary of the bug" (failure: <failure_scenario>)
2. other.py:45 — "summary of the bug" (failure: <failure_scenario>)
```

## Step 1.4: Spawn Risk Classifier (MODE=self-find only)

**SKIP this step when `MODE=consume-findings`** — `/code-review` already ran at close; the extra classifier call is wasted (sprint-103 lesson).

On `MODE=self-find`, spawn `xp-risk-classifier` exactly once. Pass the diff + the `## Changed Files` block from preload. The classifier returns `RISK=high` or `RISK=low` on its **first line** — parse strictly (read only the first line; narrative tails legitimately contain "RISK" as prose). An optional second line `SIGNALS=<comma-list>` may name elevated angles.

```
Agent(subagent_type: "xp-agents:xp-risk-classifier",
      prompt: "## Diff\n<diff>\n\n## Changed Files\n<list from preload>")
```

## Step 1.5: Build Reviewer Prompt and Spawn (single-spawn, optionally enriched)

Build the `xp-code-reviewer` prompt now. In `self-find` mode pass `## Code-Review Findings\nNone — self-find correctness` so the reviewer takes its self-find branch. **If Step 1.4 returned `RISK=high`**, prepend a verbatim `## Review Focus` block naming the elevated angle (default: `state/lifecycle/concurrency`). The agent's Section 1c recognizes the block and elevates the listed angles. On `RISK=low` (or MODE=consume-findings), spawn without the enrichment.

**Single-spawn invariant.** Exactly ONE `xp-code-reviewer` spawn per cycle. Do NOT fan-out into multiple parallel spawns. Sprint-103's 3-spawn fan-out had irreducible coordination races (filesystem writes, SMM appends, dedupe-key fragility); single-spawn enriched avoids all of them.

```
Agent(
  subagent_type: "xp-agents:xp-code-reviewer",
  prompt: "## Diff\n<diff>\n\n## Code-Review Findings\n<numbered list, or 'None — self-find correctness'>\n\n## Existing Debt\n<debt>\n\n## SMM Directory\nSMM_DIR=<path>\n\n[if RISK=high]\n## Review Focus\nstate/lifecycle/concurrency\n\nReview all four areas: correctness, drift, debt, reuse/quality/efficiency + XP values."
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
