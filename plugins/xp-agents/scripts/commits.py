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
import resolution
import security
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
    cwd: str, last_review_commit: str, command: str = ""
) -> list[str]:
    """Get deduplicated code files changed since last review + staged.

    Combines git diff --cached --name-only with git diff --name-only
    {last_review_commit}..HEAD (if a prior commit exists). Filters
    through security.is_code_file(). Returns empty list on git failure.
    """
    diff_commands: list[list[str]] = [["git", "diff", "--cached", "--name-only"]]

    if last_review_commit:
        diff_commands.append(
            ["git", "diff", "--name-only", f"{last_review_commit}..HEAD"]
        )

    # If the command includes 'git add' or 'git commit -a', also check
    # unstaged tracked changes (same pattern as security.has_staged_code_files)
    if re.search(r"\bgit\s+add\b", command) or re.search(
        r"\bgit\s+commit\s+-a", command
    ):
        diff_commands.append(["git", "diff", "--name-only"])

    all_files: set[str] = set()
    try:
        for cmd in diff_commands:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                cwd=cwd,
            )
            if result.returncode != 0:
                return []
            for f in result.stdout.strip().splitlines():
                f = f.strip()
                if f:
                    all_files.add(f)
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []

    return [f for f in sorted(all_files) if security.is_code_file(f)]


def get_uncommitted_code_files(cwd: str) -> list[str]:
    """Get non-test code files with uncommitted changes (staged + unstaged).

    Used by the post-green-tests nudge to determine if a commit is warranted.
    Returns empty list on any git failure.
    """
    try:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []

    all_files: set[str] = set()
    for result in (staged, unstaged):
        if result.returncode == 0:
            for f in result.stdout.strip().splitlines():
                f = f.strip()
                if f:
                    all_files.add(f)

    if not all_files:
        return []

    from pre_tool_write import is_test_file

    return [
        f for f in sorted(all_files) if security.is_code_file(f) and not is_test_file(f)
    ]
