#!/usr/bin/env python3
"""Milestone-scoped acceptance-surface coverage.

`uncovered_touched_surfaces` checks a milestone's `surfaces_touched`
against the project's `acceptance_surfaces`, returning the touched names whose
status is not 'covered' — a 'gap' surface, or a name absent from
acceptance_surfaces entirely. /xp-sprint-start emits one coverage concern
per returned surface. The `uncovered` CLI subcommand loads the plan, finds
the milestone by number, and prints the list as a JSON array.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import execution_plan_store
from scaffold_detect import read_acceptance_surfaces


def uncovered_touched_surfaces(milestone: dict, smm_dir: Path) -> list[str]:
    """Return touched surfaces that are not covered, in declared order."""
    surfaces = read_acceptance_surfaces(smm_dir)
    covered = {
        s["name"]
        for s in surfaces
        if isinstance(s, dict) and s.get("status") == "covered" and "name" in s
    }
    return [n for n in milestone.get("surfaces_touched", []) if n not in covered]


def _cmd_uncovered(args: argparse.Namespace) -> int:
    plan = execution_plan_store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1
    milestone = execution_plan_store.find_milestone(plan, args.milestone)
    if milestone is None:
        print(f"No milestone with number {args.milestone}", file=sys.stderr)
        return 1
    print(json.dumps(uncovered_touched_surfaces(milestone, args.smm_dir)))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Milestone surface-coverage CLI")
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    sub = parser.add_subparsers(dest="command", required=True)

    unc = sub.add_parser(
        "uncovered",
        help="Print a milestone's uncovered touched surfaces as a JSON array",
    )
    unc.add_argument("--milestone", type=int, required=True, help="Milestone number")

    args = parser.parse_args()
    dispatch = {"uncovered": _cmd_uncovered}
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
