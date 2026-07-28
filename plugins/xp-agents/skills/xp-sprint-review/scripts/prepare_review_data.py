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
import execution_plan_store  # noqa: E402
import sprint_store  # noqa: E402
from execution_plan_schema import PLAN_FILENAME  # noqa: E402
from sprint_schema import SPRINT_FILENAME  # noqa: E402


def run(smm_dir: Path, target_path: Path) -> dict | None:
    """Prepare sprint review input data and write it to ``target_path``.

    Returns the review data dict on success, None if sprint.json
    is missing or malformed.
    """
    sprint_data = sprint_store.load_sprint(smm_dir)
    if sprint_data is None or not sprint_data["sprint_id"]:
        return None

    # Execution plan path — agent uses plan_cli.py to update status.
    # plan_exists() owns the exists-and-not-a-symlink rule, but it is NOT total:
    # `Path.exists` and `Path.is_symlink` propagate EACCES on every interpreter
    # before 3.14, whose ignore list is only ENOENT/ENOTDIR/EBADF/ELOOP. One
    # sudo'd run leaving the SMM dir root-owned is enough, and an unreadable
    # plan must degrade to "no plan" rather than traceback the whole preload.
    # `migration_lock.lock_state` documents the same stdlib behaviour; an
    # earlier comment here claimed the opposite.
    try:
        plan_present = execution_plan_store.plan_exists(smm_dir)
    except OSError:
        plan_present = False
    plan_str = str(smm_dir / PLAN_FILENAME) if plan_present else ""

    counts = sprint_store.count_by_status(sprint_data)
    velocity = sprint_store.compute_velocity(sprint_data)

    review_input = {
        "sprint_id": sprint_data["sprint_id"],
        "goal": sprint_data["goal"],
        "started": sprint_data["started"],
        "stories_by_status": counts,
        "velocity": velocity,
        "milestone": sprint_data.get("milestone", ""),
        "sprint_path": str(smm_dir / SPRINT_FILENAME),
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
