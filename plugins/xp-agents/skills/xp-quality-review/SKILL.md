---
name: xp-quality-review
description: >-
  Post-simplify quality review. Reviews code changes for skipped simplify
  recommendations and Clean Code violations. Fixes issues or records debt.
  Triggered by the quality review stop gate after /simplify completes.
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

!`${CLAUDE_SKILL_DIR}/scripts/preload.sh`

# Quality Review

You are performing a post-simplify quality review. The `/simplify` skill just ran on the code changes shown above. Your job is to catch what was missed.

## Step 1: Review Simplify Results

Look back through the conversation for what `/simplify` recommended. For each recommendation:
- **Applied?** Move on.
- **Skipped?** Read the file and evaluate whether it should have been applied. If yes, apply it now. If there was a good reason to skip it, record it as a `debt` event.

## Step 2: Clean Code Review

Read each modified code file (from the diff above) and check for:

### Single Responsibility
- Does each function do exactly one thing?
- Can you describe what the function does without using "and"?
- If a function has multiple responsibilities, extract them.

### Small Functions
- Are functions short enough to understand at a glance?
- Is there only one level of abstraction per function?
- Extract deeply nested logic into well-named helper functions.

### Meaningful Names
- Do variable names reveal intent? (`remaining_retries` not `r`)
- Do function names describe what they do? (`validate_user_input` not `check`)
- Are there misleading names that don't match behavior?

### DRY (Don't Repeat Yourself)
- Is there duplicated logic that should be extracted?
- Are there copy-pasted blocks with minor variations?
- But remember: three similar lines are better than a premature abstraction.

### Dead Code
- Unused imports?
- Unreachable branches?
- Commented-out code?
- Variables assigned but never read?

### Error Handling
- Are exceptions swallowed silently (empty except blocks)?
- Is error handling at system boundaries (user input, file I/O, network)?
- Are error messages actionable?

## Step 3: Take Action

For each finding:

### Fix it directly (preferred — courage)
Edit the file to address the issue. Run tests afterward to verify.

### Record as technical debt
If the fix is too large for this review or would change behavior:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "debt" \
  --agent "xp-quality-review" \
  --content "Description of what needs fixing and why" \
  --files '["path/to/file.py"]'
```

## Step 4: Record Summary

After reviewing all files, record a summary:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-quality-review" \
  --content "Quality review complete. Fixed: [list]. Debt recorded: [list]. No issues: [list]." \
  --working-on '[]'
```

## Guidelines

- **Be honest.** If something is wrong, fix it. Don't soften real issues.
- **Be practical.** Don't flag style issues (that's the linter's job). Focus on structural and behavioral issues.
- **Be efficient.** Don't rewrite working code for aesthetics. Fix real problems.
- **Run tests** after any changes to verify nothing breaks.
- If all code is clean, just record the summary and move on. No issues is the best outcome.
