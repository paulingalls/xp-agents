#!/usr/bin/env python3
"""Save retrospective analysis: write event + file.

Accepts Keep/Fix/Try JSON on stdin, writes:
1. Timestamped JSON file to $SMM_DIR/retrospectives/
2. Retrospective event to events.jsonl

Outputs EVENT_ID=<id> and RETRO_FILE=<path> to stdout.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _append_impl
import _common


def run(kft_data: dict | None, smm_dir: Path | None = None) -> dict[str, str] | None:
    """Save retrospective analysis to event log and file.

    Args:
        kft_data: Keep/Fix/Try analysis dict with keep/fix/try arrays.
        smm_dir: SMM directory (auto-resolved if None).

    Returns:
        Dict with event_id and retro_file on success, None on failure.
    """
    if not isinstance(kft_data, dict):
        print("Error: input must be a JSON object", file=sys.stderr)
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        print("Error: could not resolve SMM directory", file=sys.stderr)
        return None

    # Build content summary
    keep_count = len(kft_data.get("keep", []))
    fix_count = len(kft_data.get("fix", []))
    try_count = len(kft_data.get("try", []))
    content = (
        f"Session retrospective: "
        f"{keep_count} keeps, {fix_count} fixes, {try_count} tries"
    )

    # Build retrospective event
    event = _common.make_event("retrospective", "xp-retrospective", content)
    if kft_data.get("keep"):
        event["keep"] = kft_data["keep"]
    if kft_data.get("fix"):
        event["fix"] = kft_data["fix"]
    if kft_data.get("try"):
        event["try"] = kft_data["try"]

    # Validate via _append_impl (single source of truth for schema)
    errors = _append_impl.validate_event(event)
    if errors:
        for err in errors:
            print(f"Validation error: {err}", file=sys.stderr)
        return None

    # Write event to events.jsonl (append_safe swallows lock errors)
    _common.append_safe(smm_dir, event)

    # Use event timestamp for the file (avoids divergent timestamps)
    ts_str = event["ts"]
    filename = ts_str.replace(":", "-").replace("+", "_")[:19] + ".json"
    retro_dir = smm_dir / "retrospectives"
    retro_dir.mkdir(exist_ok=True)
    retro_file = retro_dir / filename

    file_data = {
        "timestamp": ts_str,
        "keep": kft_data.get("keep", []),
        "fix": kft_data.get("fix", []),
        "try": kft_data.get("try", []),
    }
    if "analysis_notes" in kft_data:
        file_data["analysis_notes"] = kft_data["analysis_notes"]

    _common.write_json_atomic(retro_file, file_data)

    # Clean up retro input — it's been consumed
    (smm_dir / ".retro-input.json").unlink(missing_ok=True)

    return {"event_id": event["id"], "retro_file": str(retro_file)}


def main() -> None:
    """CLI entry point: read JSON from stdin, save retrospective."""
    try:
        kft_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(1)

    result = run(kft_data)
    if result is None:
        sys.exit(1)

    print(f"EVENT_ID={result['event_id']}")
    print(f"RETRO_FILE={result['retro_file']}")


if __name__ == "__main__":
    main()
