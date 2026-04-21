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
import retro_schema
from event_schema import RETRO_ACTION_SESSION_DONE, RETRO_ACTION_SPRINT_DONE


def run(
    kft_data: dict | None,
    smm_dir: Path | None = None,
    *,
    agent_id: str = "xp-retrospective",
    prefix: str = "Session retrospective",
    cleanup_file: str = _common.RETRO_INPUT_FILENAME,
    retro_kind: str = "session",
) -> dict[str, str] | None:
    """Save retrospective analysis to event log and file.

    Args:
        kft_data: Keep/Fix/Try analysis dict with keep/fix/try arrays.
        smm_dir: SMM directory (auto-resolved if None).
        agent_id: Agent ID for the event (default: session retro agent).
        prefix: Content prefix (default: "Session retrospective").
        cleanup_file: Input file to clean up after save.
        retro_kind: "session" or "sprint". Written to metadata.action so the
            session-start watermark scanner can distinguish kinds. Defaults
            to "session" for backwards compatibility with existing callers.

    Returns:
        Dict with event_id and retro_file on success, None on failure.
    """
    if not isinstance(kft_data, dict):
        print("Error: input must be a JSON object", file=sys.stderr)
        return None

    # Normalize: accept strings in keep/fix/try arrays, wrap as objects
    for field in ("keep", "fix", "try"):
        items = kft_data.get(field, [])
        if isinstance(items, list):
            kft_data[field] = [
                {"content": item} if isinstance(item, str) else item for item in items
            ]

    retro_errors = retro_schema.validate_retro(kft_data)
    if retro_errors:
        for err in retro_errors:
            print(f"Retro schema error: {err}", file=sys.stderr)
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        print("Error: could not resolve SMM directory", file=sys.stderr)
        return None

    # Build content summary
    keep_count = len(kft_data.get("keep", []))
    fix_count = len(kft_data.get("fix", []))
    try_count = len(kft_data.get("try", []))
    content = f"{prefix}: {keep_count} keeps, {fix_count} fixes, {try_count} tries"

    action = (
        RETRO_ACTION_SPRINT_DONE
        if retro_kind == "sprint"
        else RETRO_ACTION_SESSION_DONE
    )
    event = _common.make_event(
        "retrospective", agent_id, content, metadata={"action": action}
    )
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
    (smm_dir / cleanup_file).unlink(missing_ok=True)

    return {"event_id": event["id"], "retro_file": str(retro_file)}


def main() -> None:
    """CLI entry point: read JSON from stdin, save retrospective."""
    import argparse

    parser = argparse.ArgumentParser(description="Save retrospective analysis")
    parser.add_argument(
        "--smm-dir",
        type=Path,
        help="SMM directory (auto-resolved from CLAUDE_PLUGIN_DATA if omitted)",
    )
    parser.add_argument(
        "--agent",
        default="xp-retrospective",
        help="Agent ID for the event (default: xp-retrospective)",
    )
    parser.add_argument(
        "--prefix",
        default="Session retrospective",
        help="Content prefix (default: Session retrospective)",
    )
    parser.add_argument(
        "--cleanup-file",
        default=_common.RETRO_INPUT_FILENAME,
        help="Input file to clean up after save",
    )
    parser.add_argument(
        "--retro-kind",
        default="session",
        choices=["session", "sprint"],
        help=(
            "Retro kind: 'session' or 'sprint'. Written to metadata.action so "
            "the session-start watermark scanner distinguishes kinds."
        ),
    )
    args = parser.parse_args()

    try:
        kft_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(1)

    smm_dir = args.smm_dir if args.smm_dir else None
    result = run(
        kft_data,
        smm_dir=smm_dir,
        agent_id=args.agent,
        prefix=args.prefix,
        cleanup_file=args.cleanup_file,
        retro_kind=args.retro_kind,
    )
    if result is None:
        sys.exit(1)

    print(f"EVENT_ID={result['event_id']}")
    print(f"RETRO_FILE={result['retro_file']}")


if __name__ == "__main__":
    main()
