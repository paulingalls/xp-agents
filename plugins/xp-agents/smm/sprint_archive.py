#!/usr/bin/env python3
"""Archive sprint.json into sprints/, and read the newest one back.

Sibling module to sprint_store.py — sprint_store.py is at the 500-line cap,
so archive() lives here instead of growing that file. Mirrors
execution_plan_store.archive() exactly.

Reading is here too, with the writing, because the two share one contract:
what `archive()` names is what `load_latest()` has to find again.
"""

import json
from pathlib import Path

from archive import archive_json
from sprint_schema import SPRINT_FILENAME

_ARCHIVE_GLOB = "sprint_*.json"


def archive(smm_dir: Path) -> Path | None:
    """Move sprint.json to sprints/ with a timestamp.

    Returns the archived file path, or None if no sprint exists.
    """
    return archive_json(smm_dir, SPRINT_FILENAME, "sprints", "sprint")


def _newest_first(path: Path) -> tuple[str, int]:
    """Sort key placing the most recently archived sprint first.

    Plain filename order is WRONG for a same-second collision: `archive_json`
    appends `-1`, `-2`, ... and `-` (0x2D) sorts before `.` (0x2E), so the
    unsuffixed FIRST archive would outrank the `-1` that came after it. Split
    the suffix off and compare it numerically.
    """
    stem = path.stem
    ts, _, collision = stem.partition("-")
    try:
        index = int(collision) if collision else 0
    except ValueError:
        index = 0
    return (ts, index)


def load_latest(smm_dir: Path) -> dict | None:
    """The newest READABLE archived sprint, or None when there is none.

    Skips an unreadable or non-object archive rather than stopping at it: a
    truncated newest file must not hide a usable predecessor, because the
    caller's alternative is not "try again" but "carry nothing forward".
    """
    sprints_dir = smm_dir / "sprints"
    if not sprints_dir.is_dir():
        return None
    try:
        candidates = sorted(
            sprints_dir.glob(_ARCHIVE_GLOB), key=_newest_first, reverse=True
        )
    except OSError:
        return None
    for path in candidates:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None
