#!/usr/bin/env python3
"""The commit-gate sequence for `git commit` — split from pre_tool_bash.py to
keep that file under the 500-line cap (the same move already made for
`pre_tool_bash_branch_delete.py` and `pre_tool_bash_reviewer_guard.py`).

Runs, in order, on every recognized commit: the unreachable-target refusal (both
legs — `git -C` and `cd`), the tier-1 deterministic secret scan, the staged-lint
advisory, the review-cycle gate (with its story-cadence deferral), the
protected/sprint-branch guard, and the verify-touch nudge. The order is
load-bearing — tier-1 fires before the review-cycle gate so a deterministic
secret still blocks a commit that already has clean review flags, and the
unreachable-target refusal fires before any git read so no gate below it ever
runs against the wrong repo.

`commit_gate_parts` is the single entry point; `pre_tool_bash.run` calls it
once per Bash command and extends its own `parts` with the result. The
is_git_commit check lives INSIDE this function (not at the call site) so the
call site stays a one-liner regardless of what this module grows into.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# Nothing below imports from smm/, but this module is imported by pre_tool_bash
# BEFORE its own smm-side imports resolve. Inserting scripts/ alone would leave
# scripts/ ahead of smm/ and silently flip which directory wins for `resolution`,
# `story_done_gate`, and `event_schema`. Mirror the sibling modules' two inserts
# so import precedence is exactly what it was before the split.
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import branching
import commits
import git_commits
import identity
import markers
import security_patterns
import security_scanner
import staged_lint

# Straight from commit_command rather than through the `commits` facade that
# re-exports its siblings. `commits.py` sits at 449 lines against a 450 band
# floor, so a two-line re-export would push a facade into the size band and
# demand a recorded ceiling — for nothing. `commit_handling.py` already imports
# commit_command directly, so this is the established shape, not a new one.
from commit_command import cd_target_unreachable

# ---------------------------------------------------------------------------
# Verify-touch nudge
# ---------------------------------------------------------------------------


def _verify_touch_nudge(
    smm_dir: Path, effective_cwd: str, command: str, branch: str
) -> str | None:
    """Advisory when the active story's declared verify paths are untouched.

    Fails open at every step — this is a nudge, never a block. Suppressed by
    a [verify-deferred] commit (which records its own debt post-commit) and
    silent off a story branch, when the story declares no verify paths, when
    every path is already touched, or when git can't be read.

    verify_deferred is imported lazily (not top-level): pre_tool_bash loads on
    every Bash call, but only commits reach this helper, so we avoid pulling
    the post-commit dependency tree into the common path.
    """
    from verify_deferred import parse_verify_deferred, untouched_paths_for_story

    if parse_verify_deferred(commits.extract_commit_message(command)) is not None:
        return None
    story_id = identity.extract_story_id(branch)
    if not story_id:
        return None
    untouched = untouched_paths_for_story(smm_dir, effective_cwd, story_id)
    if not untouched:
        return None
    return (
        "Verify-touch advisory: no commit on this branch touches the declared "
        "acceptance-test path(s): " + ", ".join(untouched) + ". Touch them, or "
        "commit with [verify-deferred] <reason> to defer (records a debt)."
    )


# ---------------------------------------------------------------------------
# Commit gates
# ---------------------------------------------------------------------------


def commit_gate_parts(
    smm_dir: Path, command: str, cwd: str, agent_id: str
) -> list[str]:
    """Advisory parts from the commit gates; raises BlockedError on a block.

    Returns [] immediately for anything that isn't a recognized `git commit`
    invocation. Tier 1 security + lint run unconditionally on a commit, then
    the review cycle, which arms at REVIEW_CYCLE_THRESHOLD changed code
    files. There is no per-commit LLM security gate at any file count —
    close-skill Step 4 covers the cumulative diff at close.
    """
    if not git_commits.is_git_commit(command):
        return []

    parts: list[str] = []

    # EVERY git read below runs in the repo the commit will land in, not in the
    # hook's own cwd. `git -C <worktree> commit` (the form this project tells
    # agents to prefer over `cd`) stages nothing in the main checkout, so a raw
    # `cwd` makes `git diff --cached` come back empty — and an empty diff is not
    # a blocked commit, it is a SILENT one: the tier-1 scan has nothing to scan
    # and the lint gate has no files to group. Both gates no-op, unlinted and
    # unscanned bytes ship, and nothing says so. Parse the target once, here,
    # above the first read.
    effective_cwd = commits.parse_effective_cwd(command, cwd)

    # ...but the parse can only resolve a path it can SEE. A `-C` target the
    # shell would expand (`$WT`, `${W}`, `$(cmd)`, a bare `~`, a glob) reaches this
    # hook as literal text, fails `is_dir()`, and falls back to `cwd` — so
    # every gate below would read the CALLER's repo while the commit lands
    # somewhere else. That fallback is silent in the worst direction: in a
    # clean main checkout `git diff --cached` returns "", which is not None,
    # so the fail-closed four lines down never fires and the tier-1 scan,
    # the lint gate, and the review-cycle gate all no-op on an empty diff.
    # Refuse instead — the only honest answer when the destination is
    # unknowable. (PostToolUse can recover this case by matching HEAD's
    # subject against the message; pre-commit there is no HEAD to match.)
    # BOTH legs, because both decide the destination. `cd` reached this refusal
    # one story later than `-C`: it had the identical hidden-path problem, and
    # `cd "$WT" && git commit` fell back to the caller's cwd in silence. The two
    # predicates are separate rather than unioned inside one, because
    # `dash_c_unreachable` has other consumers whose meaning is `-C`-specific.
    unreachable_flag = commits.dash_c_unreachable(command)
    if unreachable_flag or cd_target_unreachable(command):
        named = "`git -C`" if unreachable_flag else "`cd`"
        raise _common.BlockedError(
            f"Cannot determine which repo this commit lands in: {named} "
            "names a path hidden behind a shell variable, command "
            "substitution, `~`, or a glob, or built by concatenating quoting "
            "forms or backslash escapes. The security scan, lint gate, and branch "
            "guard would all silently run against the wrong repo. Use a "
            "single literal path (quoting it is fine).",
            "Commit target repo unresolvable.",
        )

    # Tier 1 fires before the review-cycle gate so deterministic
    # patterns block even when /code-review and /xp-quality-review are done.
    diff = commits.get_staged_diff(effective_cwd)
    if diff is None:
        raise _common.BlockedError(
            "Tier 1 security scan could not run: `git diff --cached` failed. "
            "Resolve and retry the commit.",
            "Tier 1 fail-closed: git diff failure.",
        )
    if diff:
        findings = security_scanner.scan_diff(diff, security_patterns.V3_0_PATTERNS)
        if findings:
            lines = [
                f"  - {f.pattern_name} at {f.file_path}:{f.line_number}"
                for f in findings
            ]
            raise _common.BlockedError(
                "\n".join(
                    [
                        "Tier 1 security scan blocked this commit:",
                        *lines,
                        "",
                        "Fix the flagged lines or add `# noqa: secret`.",
                    ]
                ),
                "Tier 1 security pattern detected.",
            )

    # Single name-only call shared by the lint gate and downstream
    # checks — one fork instead of two.
    staged = commits.get_staged_files(effective_cwd)

    parts.extend(staged_lint.staged_lint_gate(staged, effective_cwd))

    cycle = markers.read_review_cycle(smm_dir, agent_id)
    code_files = commits.get_code_files_for_review(
        effective_cwd,
        cycle.get("last_review_commit", ""),
        command,
        staged_diff=diff,
    )

    if len(code_files) >= commits.REVIEW_CYCLE_THRESHOLD:
        if markers.read_review_cadence(smm_dir) == "story":
            # Story cadence: review relocates to /xp-story-close (merge).
            # Emit a visible deferral advisory instead of blocking — the
            # tier-1 security and lint gates above stay unconditional.
            parts.append(
                f"Story cadence: per-commit review deferred to "
                f"/xp-story-close ({len(code_files)} code files changed "
                f"since last review). /xp-quality-review runs at story "
                f"close."
            )
        elif not cycle.get("quality_review_done"):
            # Per-increment review is /xp-quality-review only — the
            # xp-code-reviewer it spawns self-finds correctness. The
            # workflow /code-review runs once at sprint/plan/free close.
            raise _common.BlockedError(
                f"Run /xp-quality-review before committing — "
                f"{len(code_files)} code files changed since last review.",
                "Quality review required before committing.",
            )

    stage = branching.get_branching_stage(smm_dir)
    if stage >= 1:
        branch = identity.get_current_branch(effective_cwd)
        is_escape = commits.is_escape_hatch_commit(command)
        if branching.is_protected_branch(stage, branch, smm_dir) and not is_escape:
            parts.append(
                f"You're committing directly to {branch} "
                f"(branching stage {stage}). Use a story branch, or prefix "
                f"with [release]/[chore]/[sprint-direct] for legitimate "
                f"main commits."
            )
        elif stage >= 2 and branching.is_sprint_branch(branch) and not is_escape:
            parts.append(
                f"You're committing directly to sprint branch {branch}. "
                f"Sprint branches accept merges only. Use a story branch, "
                f"or prefix with [release]/[chore]/[sprint-direct] for "
                f"legitimate post-merge work."
            )

        nudge = _verify_touch_nudge(smm_dir, effective_cwd, command, branch)
        if nudge:
            parts.append(nudge)

    return parts
