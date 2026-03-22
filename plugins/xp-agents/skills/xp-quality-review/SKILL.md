---
name: xp-quality-review
description: >-
  Post-simplify quality review. Courage accountability for skipped simplify
  recommendations, drift management against SMM Constraints, and debt-aware
  review. Triggered by the quality review stop gate after /simplify completes.
effort: high
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(*/skills/*/scripts/*)
  - Bash(*/append.sh *)
  - Bash(*/init.sh)
  - Bash(python3 -m unittest *)
---

!`CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Quality Review

You are performing a post-simplify quality review as a courageous senior engineer. The `/simplify` skill just ran (3 agents reviewed for code reuse, code quality, and efficiency). Your job is **not** to repeat that review — it's to hold the agent accountable and check alignment.

## Step 1: Courage — Review Skipped Simplify Recommendations

Look back through the conversation for what `/simplify` recommended. **Default to applying recommendations, not skipping them.** Skipping is the easy path — courage means doing the work now.

For each recommendation:
- **Applied?** Move on.
- **Skipped?** Read the file and the recommendation. Apply it unless it would **break a public API contract**.
  - Everything that can be fixed gets fixed now, we don't like debt. 
  - "It's consistent with existing code", "it's a design choice", "low severity", "pre-existing code", and "not our change" are **not valid reasons to skip**. 
  - If existing code is wrong, fix it. If a reviewer found it, it matters. If truly too large, record as `debt` with the specific reason.

## Step 2: Drift Management — Check Against SMM Constraints

Check if code changes contradict recorded decisions or conventions in the SMM's **Constraints** pillar (already in conversation context from session start).

For each decision/convention that relates to the changed files, check alignment:
- Decision says "Use REST for API" but code adds GraphQL endpoint → drift
- Convention says "All DB queries use ORM" but code adds raw SQL → drift
- Decision says "Single responsibility per module" but new code adds unrelated responsibilities → drift

For each drift found, record a concern:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "concern" \
  --agent "xp-quality-review" \
  --content "Decision drift: [describe how code contradicts decision/convention]" \
  --severity "medium"
```

If no Constraints pillar exists in the SMM, skip this step.

## Step 3: Debt Awareness — Address Existing Technical Debt

The preload above lists any existing debt events for the changed files. For each debt item:
- **If the changes touch the file and the debt is addressable now** — fix it. This is the best time.
- **If the changes make the debt worse** — fix it now.
- **If the changes are unrelated to the debt** — note it but don't block.

## Step 4: Take Action

For each finding from Steps 1-3:

### Fix it directly (preferred — courage)
Edit the files to address the issue. Run tests afterward to verify.

### Record as technical debt
If the fix is too large for this review or would change behavior:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "debt" \
  --agent "xp-quality-review" \
  --content "Description of what needs fixing and why" \
  --files '["path/to/file.py"]'
```

## Step 5: Record Summary

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" ${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-quality-review" \
  --content "Quality review complete. Fixed: [list]. Debt recorded: [list]. No issues: [list]." \
  --working-on '[]'
```

## Guidelines

- **Courage over comfort.** If a simplify recommendation was skipped, the default is to apply it. Skipping requires a concrete reason.
- **Don't repeat /simplify's work.** The 3 review agents already checked for code reuse, quality, and efficiency. Focus on what only you can do: accountability, drift, and debt.
- **Be efficient.** Don't re-read every file for style issues — that's the linter's and /simplify's job.
- **Run tests** after any changes to verify nothing breaks.
- If all code is clean, just record the summary and move on.
