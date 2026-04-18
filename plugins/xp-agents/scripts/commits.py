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

import security
from smm_schema import EVENT_ID_RE

REVIEW_CYCLE_THRESHOLD: int = 2


def parse_commit_message(tool_response: str) -> str | None:
    """Extract first line of commit message from git output."""
    match = re.search(r"\[[\w/.-]+\s+\w+\]\s+(.+)", tool_response)
    if match:
        return match.group(1).strip()
    return None


_RESOLVES_TRAILER_RE = re.compile(r"(?im)^resolves-event:[ \t]*(.*)\n?")


def extract_resolves_trailer(body: str | None) -> tuple[list[str], str]:
    """Parse Resolves-Event: trailers and return (event_ids, body_without_trailers).

    Trailer format (case-insensitive key, line-anchored):
        Resolves-Event: <12-hex-id>[, <id>...]

    Multiple trailer lines are supported; IDs are deduplicated in first-seen
    order. IDs that aren't exactly 12 lowercase-hex chars are rejected. The
    returned body has all matched trailer lines removed (including the newline)
    so callers can use it directly as the stored commit event content.
    """
    if not body:
        return [], body or ""
    ids: list[str] = []
    seen: set[str] = set()
    for match in _RESOLVES_TRAILER_RE.finditer(body):
        for raw in match.group(1).split(","):
            event_id = raw.strip().lower()
            if EVENT_ID_RE.match(event_id) and event_id not in seen:
                ids.append(event_id)
                seen.add(event_id)
    cleaned = _RESOLVES_TRAILER_RE.sub("", body)
    return ids, cleaned


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
