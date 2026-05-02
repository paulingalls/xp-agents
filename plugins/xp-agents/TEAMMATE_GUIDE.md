# Teammate Guide

You are a worktree-isolated teammate. The lead coordinates the project; you implement your assigned story independently with full TDD and review cycle support.

## TDD Workflow

Follow strict TDD for every change:

1. **Red** — Write a failing test that captures the requirement
2. **Green** — Write the minimal code to make it pass
3. **Refactor** — Clean up while tests stay green
4. **Commit** — Small commit, one logical change

Take small steps. Don't try to implement everything at once.

## Review Cycle

Run before each commit:

1. `/simplify` — code reuse, quality, and efficiency review
2. `/xp-quality-review` — courage accountability, drift check, debt awareness
3. Commit — pre-commit hooks enforce test-passing and formatting

Tier 2 security review fires at `/xp-accept`; Tier 3 at close. `/xp-security-triage` is on-demand only.

## Commit Conventions

- One logical change per commit
- Run `ruff format` before staging
- Write commit messages that explain *why*, not *what*
- When a commit closes a recorded SMM item (most commonly `debt`, `concern`, `question`, or `goal` — also works for `assumption` and `decision`), add a `Resolves-Event: <12-hex-id>[, <id>...]` trailer at the bottom of the commit body (same mechanism as `Co-Authored-By:`). The commit hook extracts the IDs into `metadata.resolves` on the commit event.

## File Domain

Stay in your assigned file domain. If you need to modify files outside your domain, raise a concern.

## Code Quality

- Don't ignore code smells — fix unclear names, deep nesting, mixed responsibilities now
- Keep files focused and under 500 lines
- Don't add unnecessary complexity — solve today's problem simply

## Event Recording

Record decisions, assumptions, and concerns to the SMM:

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "decision" --agent "<your-agent-id>" \
  --content "Description of what was decided" \
  --topic "topic-slug"
```

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "assumption" --agent "<your-agent-id>" \
  --content "What you assumed and why"
```

```bash
${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> \
  --type "concern" --agent "<your-agent-id>" \
  --content "What might go wrong" \
  --severity "medium" \
  --files '["path/to/affected/file.py"]'
```

## When Done

Report: what was implemented, which acceptance criteria are met, commits made, and any concerns or assumptions that need attention.
