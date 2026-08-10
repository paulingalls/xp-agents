#!/usr/bin/env python3
"""Low-level atomic-write primitives for SMM state files.

Split out of ``_append_impl.py`` to keep that file under the line-count cap.
Self-contained: no import of ``_append_impl`` here, on purpose — importing
back up would close a cycle, since ``_append_impl`` imports these primitives
back down at module load time (see the bottom of ``_append_impl.py``).

``LockTimeoutError``, ``LOCK_TIMEOUT_SECONDS``, ``flock_with_timeout``, and
``read_with_lock`` deliberately stay in ``_append_impl.py`` rather than moving
here: several tests patch ``_append_impl.LOCK_TIMEOUT_SECONDS`` via
``mock.patch.object`` (see ``tests/_lock_helpers.py``,
``tests/_in_place_helpers.py``), which only rebinds the name inside
``_append_impl``'s own namespace. ``flock_with_timeout`` resolves that global
through ``_effective_lock_timeout_seconds`` at acquire time, so if it lived here
instead, that patch would silently miss it and the timeout tests would hang
or behave incorrectly. Keeping the pair together preserves the patch seam.
"""

import contextlib
import json
import os
import re
import tempfile
from pathlib import Path

from append_validation import validate_agent_id


def _safe_open_nofollow(path: Path, flags: int) -> int:
    """Open a file with O_NOFOLLOW to reject symlinks."""
    return os.open(str(path), flags | os.O_NOFOLLOW, 0o600)


def write_watermark(smm_dir: Path, agent_id: str, line_count: int) -> None:
    """Atomic write of watermark via temp + rename. Validates agent_id.

    Rejects symlinks at the target path to prevent write-through attacks.
    """
    validate_agent_id(agent_id)
    wm_file = smm_dir / f".watermark-{agent_id}"

    # Reject existing symlink at target path
    if wm_file.is_symlink():
        raise OSError(f"Watermark path is a symlink: {wm_file}")

    write_text_atomic(wm_file, str(line_count))


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomic write of text content via tempfile + rename.

    Creates tempfile in same directory as target, writes content,
    sets permissions to 0o600, then atomically renames.
    """
    target_dir = path.parent
    fd, tmp = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        os.rename(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_json_atomic(path: Path, data: dict) -> None:
    """Atomic write of JSON data via tempfile + rename."""
    write_text_atomic(path, json.dumps(data))


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)
