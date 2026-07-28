# Teammate Guide

You implement your assigned story independently. You run in one of two contexts — tell them apart by your working directory:

- **Worktree** (parallel): your cwd is a `worktree-<story-id>/` dir out of the repo (beside the SMM dir), isolated from the main checkout and sibling teammates; prompt paths are relative to this worktree.
- **In-place** (solo delegation): your cwd IS the main checkout, already on your story branch — there is no worktree, so read/edit files directly and commit on the branch you are on.

## TDD Workflow

1. **Red** — Write a failing test that captures the requirement
2. **Green** — Write the minimal code to make it pass
3. **Refactor** — Clean up while tests stay green
4. **Commit** — small steps: one logical change per commit

## Review Cycle

Review cadence (commit | story) is set for the session: in commit cadence run `/xp-quality-review` before each commit; in story cadence the per-commit gate defers and `/xp-quality-review` runs at `/xp-story-close` on the cumulative diff. The commit gate names the cadence in force — read it, don't assume. Either way it spawns the independent `xp-code-reviewer`, which self-finds correctness plus reuse, quality, efficiency, courage, drift and debt. The broad `/code-review` (Workflow tool) is sprint-close only.

Security: a deterministic secret/pattern scan on staged diffs at commit; `/security-review` at close.

## Sequential Discipline

Your work is sequential — do one action, observe its result, then proceed. Batch only genuinely independent read-only calls, never dependent steps (e.g. save then verify).

## Commit Conventions

- `ruff format` before staging
- Commit messages explain *why*, not *what*
- When a commit closes a recorded SMM item (a `concern`, `debt`, `question`, `decision`, …), add a `Resolves-Event: <12-hex-id>[, <id>...]` trailer at the bottom of the commit body. The PostToolUse hook extracts IDs into `metadata.resolves`.
- Commit from a worktree with `git -C <literal-path>`, never `cd <wt> && git commit && cd -` (the cd-back beats the trailer-extract hook, breaking the link). An unresolvable `-C` is refused.
- Run `verify_acceptance.py --story <id>` before flipping a story to `reviewing` — it runs every `acceptance_execution` command in order and exits non-zero on the first red.

## File Domain

Stay in your assigned domain for work you initiate. If you must step outside, raise a concern — collision with parallel teammates is the risk.

**Reviewer-suggested edits are different.** KEEP an `xp-code-reviewer` edit outside your domain by default — it sees the whole diff. Raise a concern instead only when the edit is large (restructures, not polishes), off-topic for the diff, or in files owned by another in-progress story.

## Escalate on Ambiguity

If the spec is too ambiguous to execute safely (conflicting contracts, missing AC, undecided architecture), raise a blocking concern (`--type concern --severity high`) naming what's unclear.

It will not pause you — blocking gates do not apply to teammates, and only the lead clears one. Take the branch you can defend and state the assumption; if none is defensible, stop and say so in your final message.

## Code Quality

- Don't ignore code smells — fix unclear names, deep nesting, mixed responsibilities now
- Keep files focused and under 500 lines

## Event Recording

Record decisions, assumptions, and concerns to the SMM via `${CLAUDE_PLUGIN_ROOT}/smm/append.sh --smm-dir <SMM_DIR> --type <T> --agent <id> --content "..."`. Run `append.sh --help` for the full type list, flag set and budgets.

## When Done

Report: what shipped, which acceptance criteria are met, commits made, and any concerns or assumptions needing attention.
