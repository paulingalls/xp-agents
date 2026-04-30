#!/usr/bin/env python3
"""Security triage: marker file for commit gate, code-file classification.

Extracted from _common.py to keep security concerns in a dedicated module.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import markers

# Non-code suffixes used by is_code_file() for consistent classification
_NON_CODE_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".adoc",
        ".tex",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".csv",
        ".plist",
        ".pbxproj",
        ".xcworkspacedata",
        ".xcscheme",
        ".lock",
        ".license",
    }
)

# Dotfiles and special names — matched by full filename (case-insensitive).
# Dotfiles like .gitignore have no suffix in Python (Path(".gitignore").suffix == "").
_NON_CODE_NAMES = frozenset(
    {
        "license",
        "changelog",
        "readme",
        "makefile",
        "dockerfile",
        ".gitignore",
        ".gitattributes",
        ".env",
        ".env.example",
        ".dockerignore",
        ".editorconfig",
        ".prettierignore",
        ".eslintignore",
    }
)


def is_code_file(path: str) -> bool:
    """Return True if the file is likely code (not docs/config/images)."""
    suffix = Path(path).suffix.lower()
    if suffix in _NON_CODE_SUFFIXES:
        return False
    return Path(path).name.lower() not in _NON_CODE_NAMES


def has_staged_code_files(
    cwd: str, command: str = "", *, staged_diff: str | None = None
) -> bool:
    """Check if the commit will include production code files.

    Checks both already-staged files and files that will be staged by
    the command itself (`git add` in the same command, or `git commit -a`
    which auto-stages tracked files).

    When ``staged_diff`` is provided (the unified-diff text from
    ``commits.get_staged_diff``), staged filenames are parsed from that
    text rather than re-shelling — for callers that already hold the
    cached diff and want to avoid an extra subprocess fork.
    """
    import subprocess

    from commits import get_filenames_from_diff
    from pre_tool_write import is_test_file

    all_files: list[str] = []

    if staged_diff is not None:
        all_files.extend(get_filenames_from_diff(staged_diff))
    else:
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=cwd,
            )
            if result.returncode != 0:
                return True  # Can't determine — require triage
            all_files.extend(
                f.strip() for f in result.stdout.strip().splitlines() if f.strip()
            )
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            return True  # Can't determine — require triage

    # If the command includes 'git add' or 'git commit -a', the staged
    # index (and the cached diff text) won't reflect what will actually
    # be committed. Also check unstaged tracked changes — always shells.
    if re.search(r"\bgit\s+add\b", command) or re.search(
        r"\bgit\s+commit\s+-a", command
    ):
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=cwd,
            )
            if result.returncode != 0:
                return True
            all_files.extend(
                f.strip() for f in result.stdout.strip().splitlines() if f.strip()
            )
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            return True

    return any(is_code_file(f) and not is_test_file(f) for f in all_files)


def _strip_quoted(command: str) -> str:
    """Remove quoted strings and heredocs to avoid matching inside arguments."""
    # Strip heredocs first (<<'DELIM'...DELIM or <<DELIM...DELIM)
    s = re.sub(
        r"<<-?\s*'?(\w+)'?.*?\n.*?\1",
        "",
        command,
        flags=re.DOTALL,
    )
    # Remove escaped quotes, then quoted strings
    s = s.replace("\\'", "").replace('\\"', "")
    s = re.sub(r"'[^']*'", "", s)
    s = re.sub(r'"[^"]*"', "", s)
    return s


def is_git_commit(command: str) -> bool:
    """Detect git commit as an actual command, not inside quoted arguments."""
    return bool(re.search(r"\bgit\s+commit\b", _strip_quoted(command)))


def security_triaged_path(smm_dir: Path, agent_id: str = "main") -> Path:
    """Return path to the agent-scoped .security-triaged-<agent_id> marker."""
    return markers.marker_path(smm_dir, markers.SECURITY_TRIAGED, agent_id)


def security_triaged_exists(smm_dir: Path, agent_id: str = "main") -> bool:
    """Check if this agent's triage marker exists with valid JSON and 'ts' key."""
    if not markers.marker_exists(smm_dir, markers.SECURITY_TRIAGED, agent_id):
        return False
    data = markers.marker_read(smm_dir, markers.SECURITY_TRIAGED, agent_id)
    return isinstance(data, dict) and "ts" in data


def write_security_triaged(
    smm_dir: Path,
    agent_id: str = "main",
    *,
    exempt_reason: str | None = None,
) -> None:
    """Atomic write of this agent's triage marker with timestamp."""
    from _common import now_iso

    data = {"ts": now_iso()}
    if exempt_reason is not None:
        data["exempt_reason"] = exempt_reason
    markers.marker_write(smm_dir, markers.SECURITY_TRIAGED, data, agent_id)


def consume_security_triaged(smm_dir: Path, agent_id: str = "main") -> None:
    """Delete this agent's triage marker if it exists."""
    markers.marker_consume(smm_dir, markers.SECURITY_TRIAGED, agent_id)
