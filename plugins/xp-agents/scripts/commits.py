#!/usr/bin/env python3
"""Shared commit utilities for pre and post Bash hooks.

Provides commit detection, parsing, and file enumeration used by both
PreToolUse:Bash (gate) and PostToolUse:Bash (bookkeeping).
"""

import re
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

REVIEW_CYCLE_THRESHOLD: int = 2


def _run_git(args: list[str], cwd: str) -> str | None:
    """Run a git command, return stripped stdout or None on failure."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=5, cwd=cwd
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
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


def get_filenames_from_diff(diff_text: str) -> list[str]:
    """Parse post-image filenames from a unified diff, deduped, in first-seen order.

    Approximates `git diff --cached --name-only` for the common case:
    emits the new-side path for modifications and additions, the old-
    side path for deletions (where post is /dev/null), and the rename
    destination for renames. Does NOT parse `copy from`/`copy to` git
    copy-detection headers (rare for `--cached` since copy detection
    is off by default; cross-check before threading through copy-aware
    flows). Used to avoid re-shelling for filenames when the caller
    already has the cached unified diff in hand.
    """
    if not diff_text:
        return []

    out: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        if path and path not in seen:
            seen.add(path)
            out.append(path)

    # Walk line-by-line so we can pair `+++ /dev/null` (deleted file) with
    # the immediately-preceding `--- a/<path>` line.
    last_pre: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("--- a/"):
            last_pre = line[len("--- a/") :]
        elif line == "--- /dev/null":
            last_pre = None
        elif line.startswith("+++ b/"):
            _add(line[len("+++ b/") :])
            last_pre = None
        elif line == "+++ /dev/null":
            if last_pre is not None:
                _add(last_pre)
            last_pre = None
        elif line.startswith("rename to "):
            _add(line[len("rename to ") :])

    return out


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


def get_head_commit_hash(cwd: str) -> str | None:
    """Get current HEAD commit hash. Returns None on failure."""
    return _run_git(["git", "rev-parse", "HEAD"], cwd)


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


def _unstaged_worktree_deletions(cwd: str) -> set[str]:
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
    caller also asks `git_commits.stages_all_tracked_changes`.
    """
    out = _run_git(["git", "diff", "--name-only", "-z", "--diff-filter=D"], cwd)
    if out is None:
        return set()
    return set(_nul_paths(out))


def get_code_files_for_review(
    cwd: str,
    last_review_commit: str,
    command: str = "",
    *,
    staged_diff: str | None = None,
) -> list[str]:
    """Get deduplicated code files changed since last review + staged.

    A failed STAGED read leaves nothing to count. A failed WIDENING leg
    (`{sha}..HEAD` — `fatal: bad object` for a watermark sha from another
    repo — or the unstaged read a `git add` adds) drops only itself, because
    the gate must not undercount to zero. Pinned in
    test_review_record_owners.py.

    ``staged_diff`` is ``get_staged_diff``'s text, for a caller that already
    holds it: the staged names are parsed from it instead of re-shelling.

    Ghosts are dropped — ``_unstaged_worktree_deletions`` says what one is and
    what one is not. Every caller wants that: the coverage record is written
    from this same scan, so excluding on one side alone would shift the gate's
    current-minus-coverage arithmetic rather than fix it.
    """
    if staged_diff is not None:
        staged_names = set(get_filenames_from_diff(staged_diff))
    else:
        out = _run_git(["git", "diff", "--cached", "--name-only", "-z"], cwd)
        if out is None:
            return []
        staged_names = set(_nul_paths(out))

    all_files: set[str] = set(staged_names)

    extra_commands: list[list[str]] = []
    if last_review_commit:
        extra_commands.append(
            ["git", "diff", "--name-only", "-z", f"{last_review_commit}..HEAD"]
        )

    # If the command includes 'git add' or 'git commit -a', also check
    # unstaged tracked changes — those will be staged by the command itself.
    # GIT_PREFIX tolerates `git -C <path>` for both subcommands.
    if re.search(git_commits.GIT_PREFIX + r"add\b", command) or re.search(
        git_commits.GIT_PREFIX + r"commit\s+-a", command
    ):
        extra_commands.append(["git", "diff", "--name-only", "-z"])

    for cmd in extra_commands:
        out = _run_git(cmd, cwd)
        if out is None:
            continue
        all_files.update(_nul_paths(out))

    # Only the WIDENED names can be ghosts: a staged path is part of the commit
    # by definition, including `git add x.py && rm x.py`, where git reports an
    # unstaged deletion for content the index is about to commit. No widening,
    # nothing to filter, no fork spent asking.
    #
    # Nor is anything a ghost when the command stages everything: `git add -A`
    # makes each unstaged deletion one this commit performs (b9509b449417).
    widened = all_files - staged_names
    if widened and not git_commits.stages_all_tracked_changes(command):
        all_files -= widened & _unstaged_worktree_deletions(cwd)

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


# `-z` on all three for the reason `get_staged_files` carries it: git C-quotes
# non-ASCII paths in its default output, and a quoted `"caf\303\251.js"` fails
# `is_code_file`'s extension test (it ends `.js"`), so the file silently drops out
# of the review scope these feed. NUL separation also keeps a path with a space
# in one piece. `ls-files` spells the same flag the same way.
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

# -------------------------------------------------------------------
# A merge's incoming commits — re-exported from merged_range
# -------------------------------------------------------------------
# Moved out when the per-commit reader took this file over its sub-cap. Imported
# DOWN from here (that module imports `_run_git` back up), so this block must stay
# below `_run_git`'s definition.
from merged_range import (  # noqa: E402  intentional mid-file re-export
    merged_range_commits,
)

__all__ = [
    "REVIEW_CYCLE_THRESHOLD",
    "commit_repo_candidates",
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
    "merged_range_commits",
    "open_issues_matching_commit",
    "parse_commit_message",
    "parse_effective_cwd",
]
