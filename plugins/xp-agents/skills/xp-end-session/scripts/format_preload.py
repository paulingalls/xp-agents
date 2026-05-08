#!/usr/bin/env python3
"""Format draft_summary output as preload sections.

Thin wrapper that imports draft_summary in-process (no subprocess) and
prints the four sections preload.sh wants. Matches the 13-other-preload
convention of calling a sibling .py script from preload.sh rather than
inlining a python heredoc.
"""

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import draft_summary  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Format draft_summary output as preload sections."
    )
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    data = draft_summary.run(args.smm_dir)
    print("### CANDIDATES")
    print(data["summary"])
    print()
    print("### OPEN_QUESTIONS")
    print("\n".join(data["open_questions"]))
    print()
    print("### LIKELY_ADDRESSED")
    for item in data["likely_addressed"]:
        print(f"- {item['id']}")
        for commit_id in item["commits"]:
            print(f"  - {commit_id}")
    print()
    print("### UNCOMMITTED")
    print(data["uncommitted_count"])


if __name__ == "__main__":
    main()
