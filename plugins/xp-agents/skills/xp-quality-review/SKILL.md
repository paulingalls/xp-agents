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

## Step 1: Review Simplify Results (Courage)

Look back through the conversation for what `/simplify` recommended. **Default to applying recommendations, not skipping them.** Skipping is the easy path — courage means doing the work now.

For each recommendation:
- **Applied?** Move on.
- **Skipped?** Read the file and the recommendation. Apply it unless there is a **concrete, specific reason** not to (e.g., it would break an API contract, it requires a design discussion). "It's fine as-is" or "low severity" are not valid reasons to skip — if a reviewer found it, fix it. If truly too large to fix here, record it as `debt` with the specific reason it can't be done now.

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

## Step 3: Drift Management

Check if code changes contradict recorded decisions or conventions in the SMM:

1. Read the SMM's **Constraints** pillar (decisions and conventions)
2. For each decision/convention with a topic that relates to the changed files, check whether the code changes align or contradict
3. Examples of drift:
   - Decision says "Use REST for API" but code adds GraphQL endpoint
   - Convention says "All DB queries use ORM" but code adds raw SQL
   - Decision says "Single responsibility per module" but new code adds unrelated responsibilities

For each drift found, record a concern:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "concern" \
  --agent "xp-quality-review" \
  --content "Decision drift: [describe how code contradicts decision/convention]" \
  --severity "medium"
```

If no Constraints pillar exists in the SMM, skip this step.

## Step 4: Take Action (for Steps 1-3)

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

## Step 5: Record Summary

After reviewing all files, record a summary:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh \
  --type "status" \
  --agent "xp-quality-review" \
  --content "Quality review complete. Fixed: [list]. Debt recorded: [list]. No issues: [list]." \
  --working-on '[]'
```

## Guidelines

- **Courage over comfort.** If a simplify recommendation was skipped, the default is to apply it, not rationalize the skip. Skipping requires a concrete reason.
- **Be honest.** If something is wrong, fix it. Don't soften real issues.
- **Be practical.** Don't flag style issues (that's the linter's job). Focus on structural and behavioral issues.
- **Be efficient.** Don't rewrite working code for aesthetics. Fix real problems.
- **Run tests** after any changes to verify nothing breaks.
- If all code is clean, just record the summary and move on. No issues is the best outcome.
