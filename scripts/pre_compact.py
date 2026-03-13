#!/usr/bin/env python3
"""PreCompact hook: back up events and SMM before context compaction.

Creates timestamped copies of events.jsonl and SHARED_MENTAL_MODEL.md
in a backups/ subdirectory of the SMM directory.
"""

import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import contextlib

import _common

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core pre_compact logic. Creates backups."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    # Resolve SMM dir
    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Create backups directory with restrictive permissions
    backups_dir = smm_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.chmod(0o700)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # Back up events.jsonl (try/except avoids TOCTOU vs exists() check)
    events_file = smm_dir / "events.jsonl"
    events_backup = backups_dir / f"events-{ts}.jsonl"
    with contextlib.suppress(FileNotFoundError):
        shutil.copy2(events_file, events_backup)
        os.chmod(events_backup, 0o600)

    # Back up SHARED_MENTAL_MODEL.md
    smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"
    smm_backup = backups_dir / f"SMM-{ts}.md"
    with contextlib.suppress(FileNotFoundError):
        shutil.copy2(smm_file, smm_backup)
        os.chmod(smm_backup, 0o600)

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
