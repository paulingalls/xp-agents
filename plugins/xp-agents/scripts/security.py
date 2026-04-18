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


def has_staged_code_files(cwd: str, command: str = "") -> bool:
    """Check if the commit will include production code files.

    Checks both already-staged files (git diff --cached) and files that
    will be staged by the command itself (git add in the same command,
    or git commit -a which auto-stages tracked files).
    """
    import subprocess

    from pre_tool_write import is_test_file

    diff_commands = [["git", "diff", "--cached", "--name-only"]]

    # If the command includes 'git add' or 'git commit -a', the staged
    # index won't reflect what will actually be committed. Also check
    # unstaged tracked changes.
    if re.search(r"\bgit\s+add\b", command) or re.search(
        r"\bgit\s+commit\s+-a", command
    ):
        diff_commands.append(["git", "diff", "--name-only"])

    try:
        all_files: list[str] = []
        for cmd in diff_commands:
            result = subprocess.run(
                cmd,
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
        return any(is_code_file(f) and not is_test_file(f) for f in all_files)
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return True  # Can't determine — require triage


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
    from datetime import datetime, timezone

    data = {"ts": datetime.now(timezone.utc).isoformat()}
    if exempt_reason is not None:
        data["exempt_reason"] = exempt_reason
    markers.marker_write(smm_dir, markers.SECURITY_TRIAGED, data, agent_id)


def consume_security_triaged(smm_dir: Path, agent_id: str = "main") -> None:
    """Delete this agent's triage marker if it exists."""
    markers.marker_consume(smm_dir, markers.SECURITY_TRIAGED, agent_id)
