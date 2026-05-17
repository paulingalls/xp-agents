#!/usr/bin/env python3
"""Format draft_summary output as preload sections for /xp-end-session.

Thin wrapper: imports draft_summary in-process and prints the four sections
preload.sh consumes. Matches the convention of calling a sibling .py from
preload.sh rather than inlining a python heredoc.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import draft_summary


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
    print("### MAYBE_ADDRESSED")
    for item in data["maybe_addressed"]:
        print(f"- {item['id']}")
        for commit_hash in item["commits"]:
            print(f"  - {commit_hash}")
    print()
    print("### UNCOMMITTED")
    print(data["uncommitted_count"])


if __name__ == "__main__":
    main()
