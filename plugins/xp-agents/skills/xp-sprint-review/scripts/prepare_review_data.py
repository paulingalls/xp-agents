#!/usr/bin/env python3
"""Prepare sprint review data for the subagent.

Reads sprint.md and product_spec.md, computes velocity stats,
and writes .sprint-review-input.json for the xp-sprint-reviewer
subagent to consume.
"""

import sys
from pathlib import Path

# Resolve plugin root: scripts/ -> xp-sprint-review/ -> skills/ -> plugin root
_PLUGIN_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import _common  # noqa: E402
import sprint_parser  # noqa: E402
import sprint_state  # noqa: E402


def run(smm_dir: Path) -> dict | None:
    """Prepare sprint review input data.

    Returns the review data dict on success, None if sprint.md
    is missing or malformed.
    """
    content = sprint_state.read_sprint_content(smm_dir)
    if content is None:
        return None

    sprint_data = sprint_parser.parse_sprint_data(content)
    if not sprint_data["sprint_id"]:
        return None

    # Product spec path — agent Reads the file directly if it needs to Edit
    spec_path = smm_dir / "product_spec.md"
    spec_path_str = ""
    try:
        if spec_path.exists() and not spec_path.is_symlink():
            spec_path_str = str(spec_path)
    except OSError:
        pass

    velocity = sprint_parser.compute_velocity(sprint_data)

    review_input = {
        "sprint_id": sprint_data["sprint_id"],
        "goal": sprint_data["goal"],
        "started": sprint_data["started"],
        "stories_by_status": sprint_data["stories_by_status"],
        "velocity": velocity,
        "sprint_md_path": str(smm_dir / "sprint.md"),
        "product_spec_md_path": spec_path_str,
    }

    _common.write_json_atomic(smm_dir / ".sprint-review-input.json", review_input)
    return review_input


def main() -> None:
    """CLI entry point: prepare review data and print path."""
    import argparse

    parser = argparse.ArgumentParser(description="Prepare sprint review data")
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    result = run(args.smm_dir)
    if result is None:
        print("No sprint data available", file=sys.stderr)
        sys.exit(0)  # Graceful degradation in preload

    print(f"REVIEW_INPUT={args.smm_dir / '.sprint-review-input.json'}")


if __name__ == "__main__":
    main()
