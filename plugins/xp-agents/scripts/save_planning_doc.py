#!/usr/bin/env python3
"""Save planning doc: write system_context.md or execution_plan.md.

Parameterized atomic write for planning documents. Takes --type to
determine target filename and associated marker to clear.

Usage:
    echo '<markdown>' | python3 save_planning_doc.py --smm-dir DIR --type system_context
    echo '<markdown>' | python3 save_planning_doc.py --smm-dir DIR --type execution_plan
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import marker_names  # noqa: E402
from _append_impl import write_text_atomic  # noqa: E402

_DOC_TYPES = {
    "system_context": {
        "filename": "system_context.md",
        "marker": marker_names.NEEDS_SYSTEM_CONTEXT,
    },
    "execution_plan": {
        "filename": "execution_plan.md",
        "marker": marker_names.NEEDS_EXECUTION_PLAN,
    },
}


def run(content: str, smm_dir: Path, *, doc_type: str) -> None:
    """Write a planning document atomically and clear its marker.

    Args:
        content: Markdown content to write.
        smm_dir: SMM directory path.
        doc_type: One of "system_context" or "execution_plan".
    """
    if doc_type not in _DOC_TYPES:
        raise ValueError(
            f"Unknown doc_type: {doc_type!r}. Must be one of: {', '.join(_DOC_TYPES)}"
        )

    config = _DOC_TYPES[doc_type]
    target = smm_dir / config["filename"]

    if target.is_symlink():
        raise OSError(f"{config['filename']} is a symlink: {target}")

    write_text_atomic(target, content)

    (smm_dir / config["marker"]).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save planning document atomically",
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory path",
    )
    parser.add_argument(
        "--type",
        dest="doc_type",
        required=True,
        choices=list(_DOC_TYPES),
        help="Document type to save",
    )
    args = parser.parse_args()

    content = sys.stdin.read()
    run(content, args.smm_dir, doc_type=args.doc_type)


if __name__ == "__main__":
    main()
