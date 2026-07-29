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
from smm_schema import EVENT_ID_RE

REVIEW_CYCLE_THRESHOLD: int = 2


def parse_commit_message(tool_response: str) -> str | None:
    """Extract first line of commit message from git output."""
    match = re.search(r"\[[\w/.-]+\s+\w+\]\s+(.+)", tool_response)
    if match:
        return match.group(1).strip()
    return None


_RESOLVES_TRAILER_RE = re.compile(r"(?im)^resolves-event:[ \t]*(.*)\n?")
# Boundary-anchored twin of smm_schema.EVENT_ID_RE — keep in sync if the
# canonical event-ID format changes.
_BARE_EVENT_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")


def extract_implicit_event_ids(body: str | None, known_ids: set[str]) -> list[str]:
    """Scan commit body for bare 12-hex event IDs matching open events.

    Agents sometimes reference an event ID in prose (e.g., "closes concern
    <12-hex-id>") without the formal `Resolves-Event:` trailer. This helper
    surfaces those bare IDs so callers can accept the link and optionally
    nudge for the formal trailer.

    Only returns IDs that appear in `known_ids` — the caller supplies the
    set of open concern/question/debt event IDs. Dedups in first-seen order.
    """
    if not body or not known_ids:
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for match in _BARE_EVENT_ID_RE.finditer(body):
        event_id = match.group(0)
        if event_id in known_ids and event_id not in seen:
            ids.append(event_id)
            seen.add(event_id)
    return ids


def extract_resolves_trailer(body: str | None) -> tuple[list[str], str, bool]:
    """Parse Resolves-Event: trailers from a commit body.

    Trailer format (case-insensitive key, line-anchored):
        Resolves-Event: <12-hex-id>[, <id>...]

    Multiple trailer lines are supported; IDs are deduplicated in first-seen
    order. IDs that aren't exactly 12 lowercase-hex chars are rejected. The
    returned body has all matched trailer lines removed (including the newline)
    so callers can use it directly as the stored commit event content.

    has_trailer is True when any Resolves-Event: line was found, even if
    the value was "none" or otherwise not a valid hex ID. This distinguishes
    "developer followed the discipline but nothing to resolve" from
    "developer forgot the trailer entirely".
    """
    if not body:
        return [], body or "", False
    ids: list[str] = []
    seen: set[str] = set()
    has_trailer = False
    for match in _RESOLVES_TRAILER_RE.finditer(body):
        has_trailer = True
        for raw in match.group(1).split(","):
            event_id = raw.strip().lower()
            if EVENT_ID_RE.match(event_id) and event_id not in seen:
                ids.append(event_id)
                seen.add(event_id)
    cleaned = _RESOLVES_TRAILER_RE.sub("", body)
    return ids, cleaned, has_trailer


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


def get_commit_message_body(cwd: str) -> str | None:
    """Get full commit message body of HEAD. Returns None on failure."""
    return _run_git(["git", "log", "-1", "--format=%B"], cwd)


def get_head_commit_hash(cwd: str) -> str | None:
    """Get current HEAD commit hash. Returns None on failure."""
    return _run_git(["git", "rev-parse", "HEAD"], cwd)


def head_landing_facts(cwd: str, rev: str) -> tuple[int, int, str | None] | None:
    """How `rev` came to be: ``(committer ts, parent count, reflog action)``.

    One question — "did a commit just land here?" — so one reader, even
    though it takes two git calls. None when git cannot describe `rev` at all.

    `%ct`, not `%at`: a rebase or patch import preserves the AUTHOR date,
    while the committer date is when this history actually appeared. `%P`
    gives parents, so >1 marks a merge.

    The reflog action is `%gs`'s leading word, lowercased — `commit`,
    `commit (amend)`, `rebase (pick)`, `merge side`, `reset` — the only signal
    telling committing apart from the other ways HEAD reaches a young
    single-parent commit. None means UNAVAILABLE (no reflog, or its newest
    entry names another object) — never *permitted*: its one caller vetoes on
    absence, because allowing there fabricated events for commits the command
    never made. Do not restore the draft that called absence NO OPINION.
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
    action = subject.split(":", 1)[0].strip().lower() if logged_rev == rev else None
    return (*facts, action or None)


def merged_range_bodies(cwd: str, merge_hash: str) -> str:
    """Concatenated `%B` bodies of the commits a `--no-ff` merge brought in.

    A `--no-ff` merge always has two parents: `^1` is the target branch tip
    (already accounted for), `^2` is the merged-in source tip. Used by the
    merge-fallback commit-event builder to re-derive `Resolves-Event:`
    trailers that a teammate's per-commit events never recorded.

    Fails safe: a degenerate ff-merge (no `^2`) or any other git error
    returns "" rather than raising into the caller.
    """
    out = _run_git(
        ["git", "log", "--format=%B", f"{merge_hash}^1..{merge_hash}^2"], cwd
    )
    return out or ""


def get_code_files_for_review(
    cwd: str,
    last_review_commit: str,
    command: str = "",
    *,
    staged_diff: str | None = None,
) -> list[str]:
    """Get deduplicated code files changed since last review + staged.

    Combines staged filenames with git diff --name-only {last_review_commit}..HEAD
    (if a prior commit exists). Filters through code_files.is_code_file().
    Returns empty list on git failure.

    When ``staged_diff`` is provided (the unified-diff text from
    ``get_staged_diff``), the staged filenames are parsed from that text
    rather than re-shelling — for callers that already hold the cached
    diff and want to avoid an extra subprocess fork.
    """
    all_files: set[str] = set()

    if staged_diff is not None:
        all_files.update(get_filenames_from_diff(staged_diff))
    else:
        out = _run_git(["git", "diff", "--cached", "--name-only", "-z"], cwd)
        if out is None:
            return []
        all_files.update(_nul_paths(out))

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
            return []
        all_files.update(_nul_paths(out))

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
_GIT_STAGED = ["git", "diff", "--cached", "--name-only", "-z"]
_GIT_UNSTAGED = ["git", "diff", "--name-only", "-z"]
_GIT_UNTRACKED = ["git", "ls-files", "--others", "--exclude-standard", "-z"]
# O(1) repo probe — unlike the scans above it does not walk the worktree, so it
# still answers when they time out. That asymmetry is the whole point: it tells
# "no repo to ask about" apart from "this scan failed".
_GIT_IS_REPO = ["git", "rev-parse", "--is-inside-work-tree"]


def _changed_paths(cwd: str, cmds: list[list[str]]) -> set[str] | None:
    """Union of the path lines emitted by several git commands.

    None (not an empty set) when any git call failed, so callers can tell
    "git could not answer" apart from "nothing changed".
    """
    paths: set[str] = set()
    for cmd in cmds:
        out = _run_git(cmd, cwd)
        if out is None:
            return None
        paths.update(_nul_paths(out))
    return paths


def get_uncommitted_files(cwd: str) -> list[str] | None:
    """Every code file in flight in the working tree: staged, unstaged, OR
    untracked. Test files INCLUDED. This is the "is the tree dirty?" signal.

    Deliberately wider than ``get_uncommitted_code_files``, which answers a
    different question ("is a commit of *production* code warranted?") and so
    drops test files. Dirtiness must not: a tree dirty with only a broken test
    file is still broken work in flight, and an untracked brand-new failing
    test is the single most common shape of the TDD red step. Both read as
    CLEAN under the narrower helper — which, for the TDD gate
    (``tdd_check.find_last_test_signal``), is the disarm direction.

    Two ways to not get an answer, and they must not be conflated:

    * **There is no repo** (git absent, or not a work tree). Structural and
      permanent. Reads as CLEAN — a project git cannot answer for at all must
      not gate on a prior-session failure forever.
    * **This scan failed** (timeout). Transient, and the untracked scan walks
      the WHOLE worktree, so it is by far the likeliest ``_run_git`` timeout
      here. Returns **None** = "could not answer". Collapsing that to "no
      files" reads as a clean tree and UN-GATES a real failure, so the caller
      must be able to fail safe.

    The O(1) repo probe discriminates them: it still answers when a
    worktree-walking scan times out.
    """
    paths = _changed_paths(cwd, [_GIT_STAGED, _GIT_UNSTAGED, _GIT_UNTRACKED])
    if paths is None:
        if _run_git(_GIT_IS_REPO, cwd) is None:
            return []
        return None
    return sorted(f for f in paths if code_files.is_code_file(f))


def get_uncommitted_code_files(cwd: str) -> list[str]:
    """Get non-test code files with uncommitted changes (staged + unstaged).

    Used by the post-green-tests nudge to determine if a commit is warranted.
    Returns empty list on any git failure.
    """
    paths = _changed_paths(cwd, [_GIT_STAGED, _GIT_UNSTAGED])
    if not paths:
        return []

    from pre_tool_write import is_test_file

    return [
        f for f in sorted(paths) if code_files.is_code_file(f) and not is_test_file(f)
    ]


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
    "get_commit_message_body",
    "get_committed_files",
    "get_filenames_from_diff",
    "get_head_commit_hash",
    "get_staged_diff",
    "get_staged_files",
    "get_uncommitted_code_files",
    "get_uncommitted_files",
    "head_landing_facts",
    "is_escape_hatch_commit",
    "is_escape_hatch_message",
    "merged_range_bodies",
    "open_issues_matching_commit",
    "parse_commit_message",
    "parse_effective_cwd",
]
