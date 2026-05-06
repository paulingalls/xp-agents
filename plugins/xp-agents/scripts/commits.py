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

import _common
import code_files
import git_commits
import resolution
import worktree
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
    a1b2c3d4e5f6") without the formal `Resolves-Event:` trailer. This helper
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


def get_committed_files(cwd: str) -> list[str]:
    """Get list of files changed in the last commit."""
    out = _run_git(["git", "diff", "HEAD~1", "--name-only"], cwd)
    if out is None:
        return []
    return [f.strip() for f in out.splitlines() if f.strip()]


def get_staged_files(cwd: str) -> list[str]:
    """Get list of staged file paths via git diff --cached --name-only."""
    out = _run_git(["git", "diff", "--cached", "--name-only"], cwd)
    if out is None:
        return []
    return sorted(f.strip() for f in out.splitlines() if f.strip())


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


def open_issues_matching_commit(
    smm_dir: Path,
    commit_files: list[str],
    cwd: str,
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> list[dict]:
    """Return open concerns and debts whose files intersect commit_files.

    Used by bash_post_tool and the pre-commit probe to nudge agents to add
    `Resolves-Event:` trailers on commits that touch files listed in an
    unresolved concern or debt. Paths are normalized on both sides so
    `./scripts/foo.py`, `scripts/foo.py`, and an absolute path all match.

    When ``events`` is provided, filters from the given list without reading
    disk — used by callers that already loaded events (e.g. resolves_probe).
    When both ``events`` and ``resolutions`` are provided, skips computing
    resolutions entirely — avoids redundant work when the caller already has
    the resolution map (e.g. from ``load_events_with_resolutions``).
    """
    if not commit_files:
        return []
    if events is None:
        events, resolutions = _common.load_events_with_resolutions(smm_dir)
    elif resolutions is None:
        resolutions = resolution.compute_resolutions(events)
    resolved = resolutions["resolved_concern_ids"] | resolutions["resolved_debt_ids"]

    commit_set: set[str] = set()
    for f in commit_files:
        try:
            commit_set.add(worktree.normalize_path(f, cwd))
        except (ValueError, OSError):
            continue

    def _intersects(event_files: list) -> bool:
        if not isinstance(event_files, list):
            return False
        for f in event_files:
            if not isinstance(f, str):
                continue
            try:
                if worktree.normalize_path(f, cwd) in commit_set:
                    return True
            except (ValueError, OSError):
                continue
        return False

    return [
        e
        for e in events
        if e.get("type") in (_common.CONCERN, _common.DEBT)
        and e.get("id") not in resolved
        and _intersects(e.get("files") or [])
    ]


def get_commit_message_body(cwd: str) -> str | None:
    """Get full commit message body of HEAD. Returns None on failure."""
    return _run_git(["git", "log", "-1", "--format=%B"], cwd)


def get_head_commit_hash(cwd: str) -> str | None:
    """Get current HEAD commit hash. Returns None on failure."""
    return _run_git(["git", "rev-parse", "HEAD"], cwd)


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
        out = _run_git(["git", "diff", "--cached", "--name-only"], cwd)
        if out is None:
            return []
        all_files.update(f.strip() for f in out.splitlines() if f.strip())

    extra_commands: list[list[str]] = []
    if last_review_commit:
        extra_commands.append(
            ["git", "diff", "--name-only", f"{last_review_commit}..HEAD"]
        )

    # If the command includes 'git add' or 'git commit -a', also check
    # unstaged tracked changes — those will be staged by the command itself.
    # GIT_PREFIX tolerates `git -C <path>` for both subcommands.
    if re.search(git_commits.GIT_PREFIX + r"add\b", command) or re.search(
        git_commits.GIT_PREFIX + r"commit\s+-a", command
    ):
        extra_commands.append(["git", "diff", "--name-only"])

    for cmd in extra_commands:
        out = _run_git(cmd, cwd)
        if out is None:
            return []
        all_files.update(f.strip() for f in out.splitlines() if f.strip())

    return [f for f in sorted(all_files) if code_files.is_code_file(f)]


def get_uncommitted_code_files(cwd: str) -> list[str]:
    """Get non-test code files with uncommitted changes (staged + unstaged).

    Used by the post-green-tests nudge to determine if a commit is warranted.
    Returns empty list on any git failure.
    """
    all_files: set[str] = set()
    for cmd in (
        ["git", "diff", "--cached", "--name-only"],
        ["git", "diff", "--name-only"],
    ):
        out = _run_git(cmd, cwd)
        if out is None:
            return []
        all_files.update(f.strip() for f in out.splitlines() if f.strip())

    if not all_files:
        return []

    from pre_tool_write import is_test_file

    return [
        f
        for f in sorted(all_files)
        if code_files.is_code_file(f) and not is_test_file(f)
    ]


# Match `cd <path>` and `git -C <path>` only at a shell-statement boundary
# (start, newline, semicolon, &&, ||) so we don't pick up the literal text
# of a commit-message heredoc that happens to mention "cd /something". The
# parsed path is then validated via `is_dir()` — a second filter against
# false positives. Last match wins so `cd /A && cd -` lands back on /A
# (the cd-back token doesn't validate).
#
# `[^\s;&|]+` excludes statement-boundary chars from the captured path so
# `cd /tmp;` yields `/tmp` (not `/tmp;`) and `cd /a||true` yields `/a`.
# `is_dir()` would reject the trailing-punctuation variants anyway, but
# tightening the capture keeps the helper honest with its docstring.
_BOUNDARY = r"(?:^|[\n;]|&&|\|\|)\s*"
_PATH_TOKEN = r"([^\s;&|]+)"
_GIT_DASH_C_RE = re.compile(_BOUNDARY + r"git\s+-C\s+" + _PATH_TOKEN)
_CD_RE = re.compile(_BOUNDARY + r"cd\s+" + _PATH_TOKEN)


def parse_effective_cwd(command: str, fallback: str) -> str:
    """Return the effective cwd a git invocation in `command` ran under.

    `git -C <path>` wins (highest precedence); otherwise the last `cd <path>`
    segment whose target exists as a directory wins. Relative paths resolve
    against `fallback`. Returns `fallback` when nothing parses or the parsed
    path doesn't exist.

    Lets the post-Bash hook read HEAD from the right repo when an agent
    chained `cd <wt> && git commit && cd -` (the cd-back means input_data.cwd
    is no longer the worktree by the time the hook fires).

    Quoted strings and heredoc bodies are stripped before scanning so a
    commit message that quotes `cd /tmp` or `git -C /elsewhere` cannot
    retarget cwd — real paths inside message bodies pass `is_dir()`.
    """
    if not command:
        return fallback

    # Reuse git_commits' private quote/heredoc stripper so this function and
    # is_git_commit share one definition of "what counts as the outer command".
    scan_target = git_commits._strip_quoted(command)

    def _resolve(candidate: str) -> str | None:
        path = Path(candidate)
        if not path.is_absolute():
            path = Path(fallback) / path
        return str(path) if path.is_dir() else None

    def _last_validated(regex: re.Pattern[str]) -> str | None:
        for m in reversed(list(regex.finditer(scan_target))):
            resolved = _resolve(m.group(1))
            if resolved is not None:
                return resolved
        return None

    # Two passes encode precedence: -C beats cd. Within each kind, last
    # validated match wins so `cd /A && cd -` lands back on /A.
    for regex in (_GIT_DASH_C_RE, _CD_RE):
        resolved = _last_validated(regex)
        if resolved is not None:
            return resolved

    return fallback


_HEREDOC_MSG_RE = re.compile(
    r"-m\s+\"\$\(cat\s+<<'?\w+'?\n(.*?)\n\w+\n\)\"",
    re.DOTALL,
)
_SIMPLE_MSG_RE = re.compile(
    r"""-m\s+(?:"((?:[^"\\]|\\.)*)"|'([^']*)')""",
)


def extract_commit_message(command: str) -> str | None:
    """Extract the -m argument value from a git commit command."""
    heredoc = _HEREDOC_MSG_RE.search(command)
    if heredoc:
        return heredoc.group(1)
    m = _SIMPLE_MSG_RE.search(command)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return None


_ESCAPE_HATCH_RE = re.compile(r"^\[(release|chore|sprint-direct)\]", re.IGNORECASE)


def is_escape_hatch_commit(command: str) -> bool:
    msg = extract_commit_message(command)
    if msg is None:
        return False
    return bool(_ESCAPE_HATCH_RE.match(msg))
