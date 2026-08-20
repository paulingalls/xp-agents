#!/usr/bin/env python3
"""Shared commit utilities for pre and post Bash hooks.

Provides commit detection, parsing, and file enumeration used by both
PreToolUse:Bash (gate) and PostToolUse:Bash (bookkeeping).
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import code_files
import git_commits
from commits_issues import (
    find_addressing_commits,
    format_maybe_addressed_line,
    open_issues_matching_commit,
)
from diff_filenames import get_filenames_from_diff

REVIEW_CYCLE_THRESHOLD: int = 2


class GitUnavailable(RuntimeError):
    """git never answered, and a retry could change that — see ``strict``."""


def _run_git(
    args: list[str], cwd: str, timeout: float = 5, *, strict: bool = False
) -> str | None:
    """Run a git command, return stripped stdout or None on failure.

    ``timeout`` is PER CALL, so a caller inside a bounded hook divides its own
    budget across its reads — see `get_code_files_for_review`'s ``scan_budget_s``.

    ``strict`` raises `GitUnavailable` for the ONE failure a retry could change
    — a TIMEOUT — rather than collapsing it into the `None` that also means "git
    ran and refused". Every other shape keeps that decline: a missing binary is
    permanent, so raising there would leave a git-less checkout retrying the
    same read forever. Default False, so an unasking caller reads as before.
    """
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired as e:
        if strict:
            raise GitUnavailable(f"git did not answer within {timeout}s") from e
    except OSError:
        pass
    return None


def _nul_paths(out: str) -> list[str]:
    """The paths in a `-z` git listing, in the order git named them.

    One parser for every `--name-only -z` reader below, because the reason for
    `-z` is a property of git's OUTPUT and does not vary by caller: without it
    git C-QUOTES any path with non-ASCII or unusual bytes, so `café.js` arrives
    as the literal 12-character string `"caf\\303\\251.js"` — quotes included.
    Consumers then test THAT: `is_code_file` sees an extension of `.js"` and
    drops the file from the review scope, and `staged_lint.path_in_index` probes
    `git cat-file -e :0:<path>`, which resolves to nothing and drops the file from
    the lint groups, so its staged violations commit unlinted. Both losses are
    silent, because "absent" is also how a legitimate skip reads.

    NUL separation is the second half: a path may contain a space or a newline,
    and splitting a listing on newlines cannot survive either.
    """
    return [f for f in out.split("\0") if f]


def get_committed_files(cwd: str) -> list[str]:
    """Get list of files changed in the last commit."""
    out = _run_git(["git", "diff", "HEAD~1", "--name-only", "-z"], cwd)
    if out is None:
        return []
    return _nul_paths(out)


def get_staged_files(cwd: str) -> list[str]:
    """Get list of staged file paths via `git diff --cached --name-only -z`.

    Sorted, because callers compare and group these. See `_nul_paths` for why
    `-z` is load-bearing here rather than tidiness — this is the listing the
    commit-time lint gate routes through, and the one it drops files from.
    """
    out = _run_git(["git", "diff", "--cached", "--name-only", "-z"], cwd)
    if out is None:
        return []
    return sorted(_nul_paths(out))


def get_staged_diff(cwd: str) -> str | None:
    """Get unified diff of staged changes via git diff --cached.

    Returns None on git failure (non-zero exit, subprocess timeout,
    OSError, or missing git binary) so security-sensitive callers can
    fail closed instead of treating a failed git invocation as 'no
    findings'. Empty string means git ran and reported no staged changes.
    """
    return _run_git(["git", "diff", "--cached"], cwd)


def get_commit_message_body(cwd: str, rev: str = "HEAD") -> str | None:
    """Get full commit message body of `rev` (HEAD by default). None on failure.

    The default spells out the implicit rev the argument-less form already
    resolved, so every existing caller runs the identical git command.
    """
    return _run_git(["git", "log", "-1", "--format=%B", rev], cwd)


def get_commit_files(cwd: str, rev: str) -> list[str]:
    """Files `rev` changed against its first parent. Empty on git failure.

    Deliberately NOT a rev parameter on `get_committed_files`: that one runs
    `git diff HEAD~1`, which compares against the WORKING TREE, so a dirty
    checkout legitimately changes its answer. Naming both sides here asks the
    different question a recorder of a specific past commit needs — what that
    commit changed, whatever the tree looks like now.

    A root commit has no `~1` and reports nothing, matching what
    `get_committed_files` already does for a root HEAD.
    """
    out = _run_git(["git", "diff", "--name-only", "-z", f"{rev}~1", rev], cwd)
    if out is None:
        return []
    return _nul_paths(out)


def get_head_commit_hash(cwd: str, timeout: float = 5) -> str | None:
    """Get current HEAD commit hash. Returns None on failure.

    ``timeout``: a bounded caller pays for this read out of its own allowance.
    """
    return _run_git(["git", "rev-parse", "HEAD"], cwd, timeout=timeout)


def count_commits_since(cwd: str, rev: str) -> int | None:
    """How many commits have LANDED on HEAD's own line since ``rev``, or None if
    git cannot say.

    `--first-parent`, so a merge counts as the one commit it is rather than as
    the range it brought in: without it a five-commit base merge measured 6
    landings against callers' caps of 2, discarding what they were ageing.

    None — not 0 — when the range does not resolve (rewritten, pruned or foreign
    sha): a caller deciding whether something aged must tell "nothing landed"
    from "cannot tell".
    """
    out = _run_git(
        ["git", "rev-list", "--count", "--first-parent", f"{rev}..HEAD"], cwd
    )
    if out is None:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def head_landing_facts(cwd: str, rev: str) -> tuple[int, int, str | None] | None:
    """How `rev` came to be: ``(committer ts, parent count, reflog subject)``.

    One question — "did a commit just land here?" — so one reader, even
    though it takes two git calls. None when git cannot describe `rev` at all.

    `%ct`, not `%at`: a rebase or patch import preserves the AUTHOR date,
    while the committer date is when this history actually appeared. `%P`
    gives parents, so >1 marks a merge.

    The third element is the WHOLE `%gs`, lowercased — the only signal telling
    committing apart from the other ways HEAD reaches a young commit, and whole
    rather than cut at the colon because cutting there shipped a fabrication:
    `merge X: merge made by …` and `merge X: fast-forward` differ ONLY after it.

    None means UNAVAILABLE (no reflog, or its newest entry names another
    object) — never *permitted*: its one caller vetoes on absence, because
    allowing there fabricated events for commits the command never made. Do
    not restore the draft that called absence NO OPINION.
    """
    out = _run_git(["git", "show", "-s", "--format=%ct%x1f%P", rev], cwd)
    if not out:
        return None
    timestamp, _, parents = out.partition("\x1f")
    try:
        facts = (int(timestamp), len(parents.split()))
    except ValueError:
        return None
    entry = _run_git(["git", "reflog", "-1", "--format=%H%x1f%gs"], cwd) or ""
    logged_rev, _, subject = entry.partition("\x1f")
    return (*facts, subject.strip().lower() or None if logged_rev == rev else None)


def head_parent_count(cwd: str, rev: str) -> int | None:
    """How many parents `rev` has — >1 is a merge. None when git cannot say.

    Deliberately NOT `head_landing_facts`, which returns this number too: that
    one also spawns `git reflog` for "HOW did HEAD get here", which the
    confirmed-success path never asks. This is one `git show`.

    Takes a rev rather than reading HEAD implicitly, like its sibling above — the
    caller builds an event for a specific hash, and an implicit read could
    describe a different commit than the one being recorded.

    `is None`, not truthiness: `_run_git` returns `""` for a ROOT commit, whose
    `%P` is legitimately empty, and `None` only when the lookup failed. Testing
    truthiness would call a root commit unknowable.
    """
    out = _run_git(["git", "show", "-s", "--format=%P", rev], cwd)
    if out is None:
        return None
    return len(out.split())


def _unstaged_worktree_deletions(cwd: str, read=None) -> set[str]:
    """Paths git still holds in the INDEX that are gone from the working tree.

    The ghost the review gate used to bill for: a spike file that was
    committed, then removed from the working tree with the removal left
    unstaged. Deliberately NOT "everything absent from disk" — a staged `git rm`
    is absent too, and deleting a code file is a real change that deserves
    review. The index tells them apart: every deletion a commit actually makes
    is gone from it as well, so it is never in this set. Empty on git failure,
    which counts everything and fails toward one extra review, like every other
    leg here. Measured in test_review_ghosts.py.

    Being in this set is necessary but NOT sufficient: a path here is only a
    ghost while the command about to run leaves it unstaged, which is why the
    caller also asks `git_commits.absorbs_unstaged_changes` — the index rule
    above is the INDEX's, and `git commit <pathspec>` bypasses it.

    ``read`` is the caller's budgeted reader. It matters: this fork is a FIFTH
    git read inside a hook whose whole scan is bounded, and left on `_run_git`'s
    per-call default it put the worst case at 8.5s against a 5s budget —
    measured, by the non-vacuity pin in test_review_coverage_scan.py that exists
    to catch a read added without being paid for.
    """
    runner = read if read is not None else (lambda cmd: _run_git(cmd, cwd))
    out = runner(["git", "diff", "--name-only", "-z", "--diff-filter=D"])
    if out is None:
        return set()
    return set(_nul_paths(out))


def get_code_files_for_review(
    cwd: str,
    last_review_commit: str,
    command: str = "",
    *,
    staged_diff: str | None = None,
    include_unstaged: bool = False,
    include_untracked: bool = False,
    scan_budget_s: float | None = None,
) -> list[str]:
    """Get deduplicated code files changed since last review + staged.

    A failed STAGED read leaves nothing to count. A failed WIDENING leg
    (`{sha}..HEAD` — `fatal: bad object` for a watermark sha from another
    repo — or the unstaged read a `git add` adds) drops only itself, because
    the gate must not undercount to zero. Pinned in
    test_review_record_owners.py.

    ``staged_diff`` is ``get_staged_diff``'s text, for a caller that already
    holds it: the staged names are parsed from it instead of re-shelling.

    ``include_unstaged`` adds that leg outright, for a caller with no command
    to infer it from — the ``command`` route below is the pre-commit gate's.
    A flag, not a fake command, which would put a lie in what the regex reads.

    ``include_untracked`` adds CREATED files, which `git diff` never lists at any
    stage. Its own flag: a caller recording what a review COVERED wants the file
    the reviewer wrote, while the gate infers ``include_unstaged`` from a
    `git add <path>` that may stage none of them — and there a wider set BLOCKS.

    ``scan_budget_s`` bounds the WHOLE scan, for a caller inside a hook that
    has a budget: `_run_git`'s timeout is per call, so three legs at the default
    allow 15s inside a 5s SubagentStop, and the handler is killed mid-write.
    Split evenly across the legs that will run, counted before any of them does
    so the split cannot depend on an earlier read. None keeps the per-call
    default — the pre-commit gate is not the bounded caller.

    Ghosts are dropped — ``_unstaged_worktree_deletions`` says what one is and
    what one is not. Every caller wants that: the coverage record is written
    from this same scan, so excluding on one side alone would shift the gate's
    current-minus-coverage arithmetic rather than fix it.
    """
    # Asked once and read twice — by `wants_unstaged` here and by the ghost
    # filter at the tail. `absorbs_unstaged_changes` is the one spelling of the
    # question; see git_commits.py for the forms a hand-rolled regex misses.
    absorbs_unstaged = git_commits.absorbs_unstaged_changes(command)
    wants_unstaged = bool(
        include_unstaged or git_commits.stages_a_path(command) or absorbs_unstaged
    )
    legs = (
        int(staged_diff is None)
        + int(bool(last_review_commit))
        + int(wants_unstaged)
        + int(include_untracked)
        # The ghost read at the tail. Counted whenever it CAN run, not when it
        # will: `widened` is not known until the legs above have run, and the
        # rule above is that the split must not depend on an earlier read.
        + int(not absorbs_unstaged)
    )
    per_leg = scan_budget_s / legs if scan_budget_s is not None and legs else None
    read = (
        (lambda cmd: _run_git(cmd, cwd))
        if per_leg is None
        else (lambda cmd: _run_git(cmd, cwd, timeout=per_leg))
    )

    if staged_diff is not None:
        staged_names = set(get_filenames_from_diff(staged_diff))
    else:
        out = read(["git", "diff", "--cached", "--name-only", "-z"])
        if out is None:
            return []
        staged_names = set(_nul_paths(out))

    all_files: set[str] = set(staged_names)

    extra_commands: list[list[str]] = []
    if last_review_commit:
        extra_commands.append(
            ["git", "diff", "--name-only", "-z", f"{last_review_commit}..HEAD"]
        )

    # Unstaged tracked changes: either the caller asked outright, or the command
    # will commit them itself. `absorbs_unstaged` is asked ONCE, above, because
    # the ghost filter below reads the SAME answer — two spellings of that
    # question is how `commit -q -a` slipped past this gate, and the regex that
    # arrived on the other side of this merge (`commit\s+-a`) missed
    # `commit --all` as well.
    if wants_unstaged:
        extra_commands.append(["git", "diff", "--name-only", "-z"])

    # Created files. `--exclude-standard` so .gitignore'd build output is not
    # read as work; `--others` alone would hand back every artefact in the tree.
    if include_untracked:
        extra_commands.append(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"]
        )

    for cmd in extra_commands:
        out = read(cmd)
        if out is None:
            continue
        all_files.update(_nul_paths(out))

    # Only the WIDENED names can be ghosts: a staged path is part of the commit
    # by definition, including `git add x.py && rm x.py`, where git reports an
    # unstaged deletion for content the index is about to commit. No widening,
    # nothing to filter, no fork spent asking.
    #
    # Nor is anything a ghost when the command commits beyond the index: `git
    # add -A` and `git commit a.py` both perform the deletions they name.
    widened = all_files - staged_names
    if widened and not absorbs_unstaged:
        all_files -= widened & _unstaged_worktree_deletions(cwd, read=read)

    return [f for f in sorted(all_files) if code_files.is_code_file(f)]


def get_code_files_in_range(cwd: str, base: str) -> list[str]:
    """Code files changed in ``base...HEAD`` (merge-base diff).

    Used by the close pipeline to size the cumulative close diff and decide
    whether the broad workflow /code-review is worth running. Returns an empty
    list on git failure (no base, detached, etc.) so callers fail safe to
    "don't run the expensive review".
    """
    out = _run_git(["git", "diff", "--name-only", "-z", f"{base}...HEAD"], cwd)
    if out is None:
        return []
    return [f for f in _nul_paths(out) if code_files.is_code_file(f)]


# -------------------------------------------------------------------
# Bash-command parsing — re-exported from commit_command
# -------------------------------------------------------------------
# Bodies live in commit_command.py; this block keeps the historical
# `from commits import parse_effective_cwd` import path working.
from commit_command import (  # noqa: E402  intentional mid-file re-export
    commit_repo_candidates,
    dash_c_unreachable,
    extract_commit_message,
    is_escape_hatch_commit,
    is_escape_hatch_message,
    parse_effective_cwd,
)

# -------------------------------------------------------------------
# Commit-MESSAGE parsing — re-exported from commit_trailers
# -------------------------------------------------------------------
# Same arrangement, one file over: those three take text and return text,
# while everything above asks git. Callers keep reaching them as
# `commits.<name>`, so the split moved no call site.
from commit_trailers import (  # noqa: E402  intentional mid-file re-export
    extract_implicit_event_ids,
    extract_resolves_trailer,
    parse_commit_message,
)

# NO re-export of `merged_range` here, and that absence is load-bearing: that
# module imports `_run_git` from this one, so an import back the other way made
# the pair a CYCLE and `import merged_range` first raised ImportError. Its one
# caller reaches it directly — see test_commits_git_helpers.py.

__all__ = [
    "REVIEW_CYCLE_THRESHOLD",
    "GitUnavailable",
    "commit_repo_candidates",
    "count_commits_since",
    "dash_c_unreachable",
    "extract_commit_message",
    "extract_implicit_event_ids",
    "extract_resolves_trailer",
    "find_addressing_commits",
    "format_maybe_addressed_line",
    "get_code_files_for_review",
    "get_code_files_in_range",
    "get_commit_files",
    "get_commit_message_body",
    "get_committed_files",
    "get_filenames_from_diff",
    "get_head_commit_hash",
    "get_staged_diff",
    "get_staged_files",
    "head_landing_facts",
    "is_escape_hatch_commit",
    "is_escape_hatch_message",
    "open_issues_matching_commit",
    "parse_commit_message",
    "parse_effective_cwd",
]
