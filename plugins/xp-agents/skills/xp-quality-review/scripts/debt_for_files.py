#!/usr/bin/env python3
"""Surface debt events matching changed files for quality review context."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "smm"))

import _common
import concerns

_WATERMARK_ID = "debt-for-files"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    smm_dir = Path(args.smm_dir)
    if not args.files:
        print("(none)")
        return

    events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    if not events:
        print("(none — SMM empty)")
        return

    found = False
    for file_path in args.files:
        debts = concerns.find_issues_for_file(events, file_path, ".")
        for d in debts:
            found = True
            eid = d.get("id", "")
            content = d.get("content", "")[:120]
            print(f"- **{file_path}**: {content} [{eid}]")

    if not found:
        print("(none)")


if __name__ == "__main__":
    main()
