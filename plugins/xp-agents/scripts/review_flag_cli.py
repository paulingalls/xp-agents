#!/usr/bin/env python3
"""Set a review-cycle flag from close-skill prose.

Step 4b of the shared close pipeline runs /code-review via the Workflow tool
(async). A Workflow completion does NOT fire review_cycle_done.py (a
PostToolUse:Skill|Agent hook), so simplify_done is never set on its own. The
close skill calls this CLI when it LAUNCHES the workflow so:

  - close_cycle_stop_gate defers during the async review window
    (markers.review_mid_cycle True), and
  - the xp-quality-review preload emits MODE=consume-findings for the findings.

The flag is keyed on the cwd-resolved agent_id via
identity.resolve_agent_id_from_cwd — the SAME resolution the readers
(review_mode.py, close_cycle_stop_gate.py) use, so the write and reads line up
for the main checkout and teammate worktrees alike.

Keep in sync with markers.set_review_flag (the sanctioned marker writer) and
markers._REVIEW_FLAGS (the valid flag set mirrored in --flag choices below).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity
import markers


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--cwd", default=".")
    parser.add_argument(
        "flag",
        choices=sorted(markers._REVIEW_FLAGS),
        help="the review-cycle flag to set (e.g. simplify_done)",
    )
    args = parser.parse_args(argv)

    agent_id = identity.resolve_agent_id_from_cwd(args.cwd)
    markers.set_review_flag(Path(args.smm_dir), agent_id, args.flag)


if __name__ == "__main__":
    main()
