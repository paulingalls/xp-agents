#!/usr/bin/env python3
"""Surface unresolved plan review concerns for quality review context."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "smm"))

import _common
import resolution


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smm-dir", required=True)
    args = parser.parse_args()

    smm_dir = Path(args.smm_dir)
    events = _common.read_events_raw(smm_dir)
    if not events:
        print("(no events)")
        return

    resolved_ids = resolution.compute_resolutions(events)["resolved_concern_ids"]

    found = False
    for e in events:
        if (
            e.get("type") == "concern"
            and e.get("agent_id", "").startswith("xp-plan-reviewer")
            and e.get("id", "") not in resolved_ids
        ):
            found = True
            eid = e.get("id", "")
            severity = e.get("severity", "medium")
            content = e.get("content", "")[:200]
            print(f"- [{severity}] {content} [{eid}]")

    if not found:
        print("(no open plan review concerns)")


if __name__ == "__main__":
    main()
