#!/usr/bin/env python3
"""Archive sprint.json into sprints/ before the next sprint overwrites it.

Sibling module to sprint_store.py — sprint_store.py is at the 500-line cap,
so archive() lives here instead of growing that file. Mirrors
execution_plan_store.archive() exactly.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

from sprint_schema import SPRINT_FILENAME


def archive(smm_dir: Path) -> Path | None:
    """Move sprint.json to sprints/ with a timestamp.

    Returns the archived file path, or None if no sprint exists.
    """
    src = smm_dir / SPRINT_FILENAME
    sprints_dir = smm_dir / "sprints"
    sprints_dir.mkdir(exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = sprints_dir / f"sprint_{ts}.json"
    try:
        shutil.move(str(src), str(dest))
    except FileNotFoundError:
        return None
    return dest
