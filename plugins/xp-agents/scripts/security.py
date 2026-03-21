#!/usr/bin/env python3
"""Security triage: marker file for commit gate, code-file classification.

Extracted from _common.py to keep security concerns in a dedicated module.
"""

import contextlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import write_json_atomic

# Non-code suffixes shared with simplify_gate.py for consistent classification
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
        ".gitignore",
        ".gitattributes",
        ".env",
        ".env.example",
        ".dockerignore",
    }
)

_NON_CODE_NAMES = frozenset(
    {"license", "changelog", "readme", "makefile", "dockerfile"}
)


def is_code_file(path: str) -> bool:
    """Return True if the file is likely code (not docs/config/images)."""
    suffix = Path(path).suffix.lower()
    if suffix in _NON_CODE_SUFFIXES:
        return False
    return Path(path).name.lower() not in _NON_CODE_NAMES


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


def security_triaged_path(smm_dir: Path) -> Path:
    """Return path to the .security-triaged marker file."""
    return smm_dir / ".security-triaged"


def security_triaged_exists(smm_dir: Path) -> bool:
    """Check if triage marker exists and is not a symlink."""
    path = security_triaged_path(smm_dir)
    return path.exists() and not path.is_symlink()


def write_security_triaged(smm_dir: Path) -> None:
    """Atomic write of the triage marker with timestamp."""
    from datetime import datetime, timezone

    path = security_triaged_path(smm_dir)
    data = {"ts": datetime.now(timezone.utc).isoformat()}
    write_json_atomic(path, data)


def consume_security_triaged(smm_dir: Path) -> None:
    """Delete the triage marker if it exists."""
    path = security_triaged_path(smm_dir)
    with contextlib.suppress(OSError):
        path.unlink()
