#!/usr/bin/env python3
"""Save curated SMM: write four-pillar markdown atomically + update watermark.

Accepts markdown on stdin, writes SHARED_MENTAL_MODEL.md atomically,
and updates the curation watermark with the current event count.

Usage:
    echo '<markdown>' | python3 save_smm.py --smm-dir DIR
"""

import argparse
import contextlib
import os
import sys
import tempfile
from pathlib import Path

# Add smm/ to path so we can import materialize
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import materialize  # noqa: E402


def run(content: str, smm_dir: Path) -> None:
    """Write curated SMM and update curation watermark.

    Args:
        content: Four-pillar markdown to write.
        smm_dir: SMM directory path.
    """
    target = smm_dir / "SHARED_MENTAL_MODEL.md"

    # Reject symlinks
    if target.is_symlink():
        raise OSError(f"SMM path is a symlink: {target}")

    # Atomic write via tempfile + rename
    fd, tmp = tempfile.mkstemp(dir=smm_dir, suffix=".smm.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        os.rename(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise

    # Update curation watermark with current event count
    events, _ = materialize.parse_events(smm_dir)
    materialize.write_curation_watermark(smm_dir, len(events), "xp-housekeeping")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save curated four-pillar SMM and update watermark"
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory path",
    )
    args = parser.parse_args()

    content = sys.stdin.read()
    run(content, args.smm_dir)


if __name__ == "__main__":
    main()
