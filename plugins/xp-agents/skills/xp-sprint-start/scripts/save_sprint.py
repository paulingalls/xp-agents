#!/usr/bin/env python3
"""Save sprint: write sprint.md atomically.

Accepts markdown on stdin, writes sprint.md to the SMM directory.
No watermark — sprint.md is not a curation artifact.

Usage:
    echo '<markdown>' | python3 save_sprint.py --smm-dir DIR
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

from _append_impl import write_text_atomic  # noqa: E402


def run(content: str, smm_dir: Path) -> None:
    """Write sprint.md atomically.

    Args:
        content: Markdown content to write.
        smm_dir: SMM directory path.
    """
    target = smm_dir / "sprint.md"

    if target.is_symlink():
        raise OSError(f"sprint.md is a symlink: {target}")

    write_text_atomic(target, content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Save sprint.md atomically")
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
