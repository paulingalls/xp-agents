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

You are performing a post-simplify quality review. The `/simplify` skill just ran (3 agents reviewed for code reuse, code quality, and efficiency). Your job is to orchestrate an independent review and resolve plan concerns.

## Step 1: Spawn Independent Code Reviewer

Gather data from the conversation and preload, then spawn the `xp-code-reviewer` subagent.

### Gather simplify findings

Look back through the conversation for what `/simplify`'s three agents found. For each finding, capture it as a quoted item — include the file, what was recommended, and whether it was applied or skipped. **Do NOT include the skip reasons** — the subagent should form its own opinion.

Format as a numbered list:
```
1. [Agent: Code Reuse] file.py: "finding text" — APPLIED
2. [Agent: Code Quality] other.py: "finding text" — SKIPPED
3. [Agent: Efficiency] file.py: "finding text" — APPLIED
...
```

### Build the prompt and spawn

Use the Agent tool to spawn the reviewer. Include:
- The simplify findings list you gathered above
- The diff from the preload output above
- The debt data from the preload output above (if any)
- The SMM_DIR path from the preload

```
Agent(
  subagent_type: "xp-agents:xp-code-reviewer",
  prompt: "You are reviewing code changes. Here is your input:

## Diff
<paste diff from preload>

## Simplify Findings
<paste your numbered findings list>

## Existing Debt for Changed Files
<paste debt data from preload, or 'None'>

## SMM Directory
SMM_DIR=<SMM_DIR from preload>

Review all four areas per your instructions: simplify accountability, drift management, debt awareness, and XP values code review."
)
```

Wait for the subagent to complete. Its findings will be returned as a tool result.

## Step 2: Resolve Plan Review Concerns

The preload above lists open concerns from the plan reviewer. For each concern:
- **If the code changes address it** — resolve it:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" \
  --agent "xp-quality-review" \
  --content "Resolved: [brief description of what was addressed]" \
  --working-on '[]' \
  --metadata '{"resolves": ["<concern-event-id>"]}'
```

- **If the concern is still open** — leave it.

If no open plan concerns are listed in the preload, skip this step.

## Step 3: Act on Subagent Findings

Review the xp-code-reviewer's summary. For each finding:

### Fix it directly (preferred — courage)
Edit the files to address the issue. Run tests afterward to verify.

### Already recorded
If the subagent already recorded concerns or debt via append.sh, no further action needed for those items.

### Record remaining debt
If a fix is too large for this review:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "debt" \
  --agent "xp-quality-review" \
  --content "Description of what needs fixing and why" \
  --files '["path/to/file.py"]'
```

## Step 4: Record Summary

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "status" \
  --agent "xp-quality-review" \
  --content "Quality review complete. Fixed: [list]. Debt recorded: [list]. No issues: [list]." \
  --working-on '[]'
```

## Guidelines

- **Independence is the point.** The xp-code-reviewer subagent has fresh context — it didn't write the code and doesn't know why findings were skipped. Trust its judgment.
- **Courage over comfort.** If the subagent says a skipped finding should be applied, default to applying it.
- **Don't repeat work.** The subagent handles simplify accountability, drift, debt, and XP-lens review. You handle plan concerns and act on findings.
- **Run tests** after any changes to verify nothing breaks.
- If the subagent reports all code is clean, just record the summary and move on.
