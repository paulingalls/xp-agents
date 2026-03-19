#!/usr/bin/env python3
"""Security review tracker: hash validation, tracker files, code-change detection.

Extracted from _common.py to keep security concerns in a dedicated module.
"""

import contextlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import write_json_atomic

_COMMIT_HASH_RE = re.compile(r"^[0-9a-f]{7,40}$")


def get_head_hash(cwd: str = ".") -> str | None:
    """Get current HEAD commit hash. Returns None on failure."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            timeout=5,
        ).strip()
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return None


def security_tracker_path(smm_dir: Path, commit_hash: str) -> Path:
    """Build tracker path. Validates hash format (^[0-9a-f]{7,40}$)."""
    if not _COMMIT_HASH_RE.match(commit_hash):
        raise ValueError(f"Invalid commit hash: {commit_hash!r}")
    return smm_dir / f".security-reviewed-{commit_hash}"


def security_tracker_exists(smm_dir: Path, commit_hash: str) -> bool:
    """Check if tracker exists and is not a symlink."""
    try:
        path = security_tracker_path(smm_dir, commit_hash)
    except ValueError:
        return False
    return path.exists() and not path.is_symlink()


def write_security_tracker(smm_dir: Path, commit_hash: str) -> None:
    """Atomic write + cleanup old trackers."""
    from datetime import datetime, timezone

    path = security_tracker_path(smm_dir, commit_hash)
    data = {
        "commit_hash": commit_hash,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(path, data)
    _cleanup_old_security_trackers(smm_dir, commit_hash)


def _cleanup_old_security_trackers(smm_dir: Path, keep_hash: str) -> None:
    """Remove .security-reviewed-* files except current."""
    keep_name = f".security-reviewed-{keep_hash}"
    for f in smm_dir.glob(".security-reviewed-*"):
        if f.name == keep_name:
            continue
        # Validate suffix is a commit hash before deleting
        suffix = f.name.removeprefix(".security-reviewed-")
        if _COMMIT_HASH_RE.match(suffix):
            with contextlib.suppress(OSError):
                f.unlink()


def mark_security_reviewed(smm_dir: Path, cwd: str = ".") -> None:
    """Get HEAD hash and write security tracker. No-op on failure."""
    head_hash = get_head_hash(cwd)
    if head_hash is not None:
        write_security_tracker(smm_dir, head_hash)


def find_last_reviewed_hash(smm_dir: Path) -> str | None:
    """Find the commit hash from the most recent security tracker file."""
    for f in smm_dir.glob(".security-reviewed-*"):
        if f.is_symlink():
            continue
        suffix = f.name.removeprefix(".security-reviewed-")
        if _COMMIT_HASH_RE.match(suffix):
            return suffix
    return None


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


def diff_has_code_changes(reviewed_hash: str, head_hash: str, cwd: str = ".") -> bool:
    """Check if git diff between two commits contains code file changes.

    Returns True if any changed file passes is_code_file(). Returns True
    on error (fail-open would skip review; fail-closed is safer).
    """
    try:
        result = subprocess.check_output(
            ["git", "diff", "--name-only", f"{reviewed_hash}..{head_hash}"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            timeout=5,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return True  # fail-closed: assume code changes on error

    files = [f.strip() for f in result.strip().splitlines() if f.strip()]
    if not files:
        return False
    return any(is_code_file(f) for f in files)
