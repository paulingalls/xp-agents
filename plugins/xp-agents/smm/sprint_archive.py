#!/usr/bin/env python3
"""Archive sprint.json into sprints/ before the next sprint overwrites it.

Sibling module to sprint_store.py — sprint_store.py is at the 500-line cap,
so archive() lives here instead of growing that file. Mirrors
execution_plan_store.archive() exactly.
"""

from pathlib import Path

from archive import archive_json
from sprint_schema import SPRINT_FILENAME


def archive(smm_dir: Path) -> Path | None:
    """Move sprint.json to sprints/ with a timestamp.

    Returns the archived file path, or None if no sprint exists.
    """
    return archive_json(smm_dir, SPRINT_FILENAME, "sprints", "sprint")
