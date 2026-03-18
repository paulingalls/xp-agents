#!/usr/bin/env python3
"""Save curated SMM: write four-pillar markdown atomically + update watermark.

Accepts markdown on stdin, writes SHARED_MENTAL_MODEL.md atomically,
and updates the curation watermark with the current event count.

Usage:
    echo '<markdown>' | python3 save_smm.py --smm-dir DIR
"""

import argparse
import sys
from pathlib import Path

# Add smm/ to path so we can import materialize and _append_impl
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import materialize  # noqa: E402
from _append_impl import write_text_atomic  # noqa: E402


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

    write_text_atomic(target, content)

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
