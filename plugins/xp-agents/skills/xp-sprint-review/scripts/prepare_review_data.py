#!/usr/bin/env python3
"""Prepare sprint review data for the subagent.

Reads sprint.json and execution_plan.json, computes velocity stats,
and writes the review input JSON to a per-invocation target path so
concurrent close skills in different worktrees never race on a shared
file. Mirrors the close-skill preload pattern (xp-sprint-close /
xp-plan-close), where preload.sh mktemps the path and passes it in.
"""

import sys
from pathlib import Path

# Resolve plugin root: scripts/ -> xp-sprint-review/ -> skills/ -> plugin root
_PLUGIN_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import _common  # noqa: E402
import sprint_store  # noqa: E402


def run(smm_dir: Path, target_path: Path) -> dict | None:
    """Prepare sprint review input data and write it to ``target_path``.

    Returns the review data dict on success, None if sprint.json
    is missing or malformed.
    """
    sprint_data = sprint_store.load_sprint(smm_dir)
    if sprint_data is None or not sprint_data["sprint_id"]:
        return None

    # Execution plan path — agent uses plan_cli.py to update status
    plan_path = smm_dir / "execution_plan.json"
    plan_str = ""
    try:
        if plan_path.exists() and not plan_path.is_symlink():
            plan_str = str(plan_path)
    except OSError:
        pass

    counts = sprint_store.count_by_status(sprint_data)
    velocity = sprint_store.compute_velocity(sprint_data)

    review_input = {
        "sprint_id": sprint_data["sprint_id"],
        "goal": sprint_data["goal"],
        "started": sprint_data["started"],
        "stories_by_status": counts,
        "velocity": velocity,
        "milestone": sprint_data.get("milestone", ""),
        "sprint_path": str(smm_dir / "sprint.json"),
        "execution_plan_path": plan_str,
    }

    _common.write_json_atomic(target_path, review_input)
    return review_input


def main() -> None:
    """CLI entry point: prepare review data and print path."""
    import argparse

    parser = argparse.ArgumentParser(description="Prepare sprint review data")
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Per-invocation tempfile path to write review input to",
    )
    args = parser.parse_args()

    result = run(args.smm_dir, args.target)
    if result is None:
        print("No sprint data available", file=sys.stderr)
        sys.exit(0)  # Graceful degradation in preload

    print(f"REVIEW_INPUT={args.target}")


if __name__ == "__main__":
    main()
