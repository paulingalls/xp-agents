#!/usr/bin/env python3
"""Prepare sprint retrospective data for the subagent.

Reads sprint.md, collects session retros from the sprint period,
computes velocity and sizing data, and writes .sprint-retro-input.json
for the xp-sprint-retro subagent to consume.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import sprint_store


def _collect_session_retros(smm_dir: Path, started: str) -> list[dict]:
    """Collect session retro files from the sprint period.

    Returns retros with timestamp >= started, sorted chronologically.
    """
    retro_dir = smm_dir / "retrospectives"
    if not retro_dir.is_dir():
        return []

    retros: list[dict] = []
    for path in sorted(retro_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        ts = data.get("timestamp", "")
        if not ts or ts[:10] < started:
            continue

        retros.append(
            {
                "timestamp": ts,
                "keep": data.get("keep", []),
                "fix": data.get("fix", []),
                "try": data.get("try", []),
            }
        )

    return retros


def run(smm_dir: Path) -> dict | None:
    """Prepare sprint retro input data.

    Returns the retro data dict on success, None if sprint.md
    is missing or malformed.
    """
    sprint_data = sprint_store.load_sprint(smm_dir)
    if sprint_data is None or not sprint_data["sprint_id"]:
        return None

    velocity = sprint_store.compute_velocity(sprint_data)
    session_retros = _collect_session_retros(smm_dir, sprint_data["started"])

    retro_input = {
        "sprint_id": sprint_data["sprint_id"],
        "goal": sprint_data["goal"],
        "started": sprint_data["started"],
        "velocity": velocity,
        "stories": sprint_data["stories"],
        "session_retros": session_retros,
        "sprint_md_path": str(smm_dir / "sprint.json"),
    }

    _common.write_json_atomic(smm_dir / ".sprint-retro-input.json", retro_input)
    return retro_input


def main() -> None:
    """CLI entry point: prepare retro data and print path."""
    import argparse

    parser = argparse.ArgumentParser(description="Prepare sprint retrospective data")
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    result = run(args.smm_dir)
    if result is None:
        print("No sprint data available", file=sys.stderr)
        sys.exit(0)  # Graceful degradation in preload

    print(f"RETRO_INPUT={args.smm_dir / '.sprint-retro-input.json'}")


if __name__ == "__main__":
    main()
