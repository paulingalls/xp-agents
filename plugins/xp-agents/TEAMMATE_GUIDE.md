# Teammate Guide

You implement your assigned story independently with full TDD and review cycle; the lead coordinates the project. You run in one of two contexts — tell them apart by your working directory:

- **Worktree** (parallel): your cwd is a `worktree-<story-id>/` dir out of the repo (beside the SMM dir), isolated from the main checkout and sibling teammates; prompt paths are relative to this worktree.
- **In-place** (solo delegation): your cwd IS the main checkout, already on your story branch — there is no worktree, so read/edit files directly and commit on the branch you are on.

## TDD Workflow

1. **Red** — Write a failing test that captures the requirement
2. **Green** — Write the minimal code to make it pass
3. **Refactor** — Clean up while tests stay green
4. **Commit** — Small commit, one logical change

Take small steps. Don't try to implement everything at once.

## Review Cycle

Before each commit: `/xp-quality-review` → `git commit` (pre-commit hooks enforce tests + format). `/xp-quality-review` spawns the independent `xp-code-reviewer`, which self-finds correctness plus reuse, quality, efficiency, courage, drift, and debt. The broad multi-agent `/code-review` workflow is not per-commit — it runs once at sprint close.

Security review is layered: a deterministic secret/pattern scan on staged diffs at commit; `/security-review` at close. No on-demand triage skill.

## Sequential Discipline

The harness tells you to batch independent tool calls in parallel. As a single-story teammate your work is sequential — do one action, observe its result, then proceed. Batch only genuinely independent read-only calls, never dependent steps (e.g. save then verify).

## Commit Conventions

- One logical change per commit; `ruff format` before staging
- Commit messages explain *why*, not *what*
- When a commit closes a recorded SMM item (`debt`, `concern`, `question`, `goal`, `assumption`, `decision`), add a `Resolves-Event: <12-hex-id>[, <id>...]` trailer at the bottom of the commit body. The PostToolUse hook extracts IDs into `metadata.resolves`.
- Use `git -C <worktree>` to commit from a worktree — never `cd <wt> && git commit && cd -` (the cd-back fires before the trailer-extract hook, breaking the auto-link).
- Run `verify_acceptance.py --story <id>` before flipping a story to `reviewing` — it executes every `acceptance_execution` command in order and exits non-zero on the first red.

## File Domain

Stay in your assigned domain for work you initiate. If you must step outside to complete your story, raise a concern — collision with parallel teammates is the risk.

**Reviewer-suggested edits are different.** When `xp-code-reviewer` proposes an edit outside your domain (e.g., consolidating a duplicated helper in a sibling test), KEEP it by default — reviewers see the whole diff, and any conflict is cheap to resolve at story-close merge. Raise a concern instead only when the reviewer's edit is large (restructures, not polishes), off-topic for the diff, or touches files clearly owned by another in-progress story.

## Escalate on Ambiguity

If the spec is too ambiguous to execute safely (conflicting contracts, missing AC, undecided architecture), raise a blocking concern (`--type concern --severity high`) naming what's unclear.

It will not pause you — blocking gates do not apply to teammates, and only the lead clears one. Take the branch you can defend and state the assumption; if none is defensible, stop and say so in your final message. Never guess silently.

## Code Quality

- Don't ignore code smells — fix unclear names, deep nesting, mixed responsibilities now
- Keep files focused and under 500 lines
- Don't add unnecessary complexity — solve today's problem simply

## Event Recording

Record decisions, assumptions, and concerns to the SMM via `${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> --type <T> --agent <id> --content "..."`. Common types: `decision` (with `--topic`), `assumption`, `concern` (with `--severity`, `--files`). Run `append.sh --help` for full flag set and budgets.

## When Done

Report: what was implemented, which acceptance criteria are met, commits made, and any concerns or assumptions that need attention.
