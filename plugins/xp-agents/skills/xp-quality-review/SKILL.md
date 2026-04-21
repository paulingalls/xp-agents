---
name: xp-quality-review
description: >-
  Post-simplify quality review. Spawns an independent xp-code-reviewer subagent
  for simplify accountability, drift management, debt awareness, and XP-lens
  code review. Resolves plan concerns inline.
effort: high
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Agent
  - Bash(*/skills/*/scripts/*)
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(python3 -m unittest *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Quality Review

Post-simplify review. `/simplify` just ran (3 agents: code reuse, quality, efficiency). You orchestrate an independent review and resolve plan concerns.

## Step 1: Pre-commit Resolves-Trailer Probe

Before spawning the reviewer, surface open concerns whose files intersect staged changes. If the commit closes one, add `Resolves-Event: <event-id>` as a commit trailer so the link lands on the first commit.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/xp-quality-review/scripts/probe_candidates.py \
  --smm-dir <SMM_DIR> --cwd $(pwd)
```

Echo candidate IDs inline so the subagent sees them in context. The script drops a `REVIEW_FINGERPRINT` marker that suppresses the duplicate post-commit nudge when the staged set + open-concern set match at commit time.

## Step 2: Spawn Independent Code Reviewer

### Gather Simplify Findings

Look back through the conversation for what `/simplify`'s three agents found. For each finding, capture: the file, what was recommended, and whether it was APPLIED or SKIPPED. **Do NOT include the skip reasons** — the subagent should form its own opinion.

Format as a numbered list — include the file, what was recommended, and the disposition:
```
1. [Agent: Code Reuse] file.py: "finding text" — APPLIED
2. [Agent: Code Quality] other.py: "finding text" — SKIPPED
3. [Agent: Efficiency] file.py: "finding text" — APPLIED
```

### Build the Prompt and Spawn

Use the Agent tool to spawn the `xp-code-reviewer` subagent. The prompt must include everything the reviewer needs for an independent assessment — it has no conversation context:

```
Agent(
  subagent_type: "xp-agents:xp-code-reviewer",
  prompt: "## Diff\n<diff from preload>\n\n## Simplify Findings\n<numbered list>\n\n## Existing Debt\n<debt from preload or 'None'>\n\n## SMM Directory\nSMM_DIR=<path>\n\nReview all four areas: simplify accountability, drift, debt, XP values."
)
```

Wait for the subagent to complete. Its findings and any recorded events will be returned as a tool result.

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

If no open plan concerns are listed in the preload, skip this step.

## Step 4: Act on Subagent Findings

Review the xp-code-reviewer's summary. For each finding:

- **Fix directly** (preferred — courage). Edit files to address the issue. Run tests afterward.
- **Already recorded** by subagent via append.sh — no further action needed.
- **Record as debt** if fix is too large for this review:
```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "debt" --agent "xp-quality-review" \
  --content "What needs fixing and why" --files '["path/to/file.py"]'
```

## Step 5: Record Summary

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" --agent "xp-quality-review" \
  --content "Quality review complete. Fixed: [list]. Debt: [list]. Clean: [list]." \
  --working-on '[]'
```

## Guidelines

- **Independence is the point.** The xp-code-reviewer subagent has fresh context — it didn't write the code. Trust its judgment.
- **Courage over comfort.** If the subagent says a skipped finding should be applied, default to applying it.
- **Don't repeat work.** The subagent handles simplify accountability, drift management, debt awareness, and XP-lens review. You handle plan concerns and act on findings.
- **Run tests** after any changes to verify nothing breaks.
- If the subagent reports all code is clean, record the summary and move on.
