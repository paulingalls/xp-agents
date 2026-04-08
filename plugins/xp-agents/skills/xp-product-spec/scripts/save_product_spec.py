#!/usr/bin/env python3
"""Save product spec: write product_spec.md atomically + clear marker.

Accepts markdown on stdin, writes product_spec.md to the SMM directory,
then clears the .needs-product-spec marker since the spec now exists.

Usage:
    echo '<markdown>' | python3 save_product_spec.py --smm-dir DIR
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import marker_names  # noqa: E402
from _append_impl import write_text_atomic  # noqa: E402


def run(content: str, smm_dir: Path) -> None:
    """Write product_spec.md atomically and clear NEEDS_PRODUCT_SPEC.

    Args:
        content: Markdown content to write.
        smm_dir: SMM directory path.
    """
    target = smm_dir / "product_spec.md"

    if target.is_symlink():
        raise OSError(f"product_spec.md is a symlink: {target}")

    write_text_atomic(target, content)

    # Clear NEEDS_PRODUCT_SPEC marker — the spec now exists
    (smm_dir / marker_names.NEEDS_PRODUCT_SPEC).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Save product_spec.md atomically")
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
