#!/usr/bin/env python3
"""Adopt / defer / drop retro Try items, wiring metadata.resolves from refs.

Parses the `[refs: id1, id2]` suffix produced by the preload's Try-item
renderer and persists the correct event shape, so the LLM no longer has
to craft `--metadata` JSON by hand (a discipline that failed four retros
in a row).

Subcommands:
  adopt  → decision event with topic + metadata.resolves
  defer  → status event, disposition=deferred, working_on=[]
  drop   → status event, disposition=dropped, working_on=[]
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
from event_schema import (  # noqa: E402
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    DISPOSITION_DROPPED,
    METADATA_KEY_DISPOSITION,
    METADATA_KEY_RESOLVES,
    validate_event,
)
from smm_schema import EVENT_ID_RE  # noqa: E402


def run(
    action: str,
    smm_dir: Path,
    content: str,
    topic: str | None = None,
    event_id: str | None = None,
) -> str:
    """Append the event and return its id.

    Retro Try actions: "adopt" | "defer" | "drop" (content-based — the
    `[refs: id1, id2]` suffix is consumed by event_builder.extract_refs_suffix
    inside _common.make_event).
    Triage actions: "triage-adopt" | "triage-defer" | "triage-drop"
    (event-id-based).
    """
    match action:
        case "adopt":
            event = _common.make_event(
                "decision",
                "xp-work-selection",
                content,
                topic=topic,
            )
        case "defer" | "drop":
            disposition = (
                DISPOSITION_DEFERRED if action == "defer" else DISPOSITION_DROPPED
            )
            event = _common.make_event(
                "status",
                "xp-work-selection",
                content,
                working_on=[],
                metadata={METADATA_KEY_DISPOSITION: disposition},
            )
        case "triage-adopt" | "triage-defer" | "triage-drop":
            if event_id is None:
                raise ValueError(f"{action} requires --event-id")
            if not EVENT_ID_RE.match(event_id):
                raise ValueError(f"Invalid event ID format: {event_id}")
            _triage_dispositions = {
                "triage-adopt": DISPOSITION_ADOPTED,
                "triage-defer": DISPOSITION_DEFERRED,
                "triage-drop": DISPOSITION_DROPPED,
            }
            disposition = _triage_dispositions[action]
            metadata: dict = {METADATA_KEY_DISPOSITION: disposition}
            if disposition != DISPOSITION_DEFERRED:
                metadata[METADATA_KEY_RESOLVES] = [event_id]
            event = _common.make_event(
                "status",
                "xp-work-selection",
                f"Triage: {disposition} {event_id[:8]}",
                working_on=[],
                metadata=metadata,
            )
        case _:
            raise ValueError(f"Unknown action: {action}")

    errors = validate_event(event)
    if errors:
        raise ValueError(f"Event validation failed: {'; '.join(errors)}")
    _common.append_safe(smm_dir, event)
    return event["id"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adopt/defer/drop a retro Try item with auto-wired resolves."
    )
    sub = parser.add_subparsers(dest="action", required=True)

    adopt = sub.add_parser("adopt", help="Record adoption as a decision event")
    adopt.add_argument("--smm-dir", type=Path, required=True)
    adopt.add_argument("--topic", required=True, help="Slugged retro-try-<slug>")
    adopt.add_argument("--content", required=True)

    defer = sub.add_parser("defer", help="Record deferral as a status event")
    defer.add_argument("--smm-dir", type=Path, required=True)
    defer.add_argument("--content", required=True)

    drop = sub.add_parser("drop", help="Record drop as a status event")
    drop.add_argument("--smm-dir", type=Path, required=True)
    drop.add_argument("--content", required=True)

    for name in ("triage-adopt", "triage-defer", "triage-drop"):
        p = sub.add_parser(name, help=f"Triage: {name.split('-')[1]}")
        p.add_argument("--smm-dir", type=Path, required=True)
        p.add_argument("--event-id", required=True, help="Event ID to triage")

    args = parser.parse_args()
    try:
        event_id = run(
            action=args.action,
            smm_dir=args.smm_dir,
            content=getattr(args, "content", ""),
            topic=getattr(args, "topic", None),
            event_id=getattr(args, "event_id", None),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(event_id)


if __name__ == "__main__":
    main()
