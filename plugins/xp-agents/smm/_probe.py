#!/usr/bin/env python3
"""Tiny config-probe helper shared across the smm and scripts layers.

Both `smm/seed_smm.py` (linter/formatter detection during SMM seeding)
and `scripts/scaffold_detect.py` (acceptance-tool detection) walk a
directory looking for known config filenames, optionally verifying a
marker substring inside the file. This module hosts the single helper
they share.

Lives in smm/ (the foundational layer) so seed_smm.py — which only
imports from smm/ — can use it without a reverse cross-layer import.
"""

from pathlib import Path


def probe_config_file(
    root: Path,
    filename: str,
    marker: str | None = None,
) -> Path | None:
    """Return root/filename if it exists (and contains marker if given).

    Reads with errors='ignore' so partial/malformed config files don't
    crash detection. Returns None if the file is missing, unreadable, or
    lacks the requested marker.
    """
    path = root / filename
    if not path.is_file():
        return None
    if marker is None:
        return path
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    return path if marker in text else None
