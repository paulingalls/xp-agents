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
import re
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
from event_schema import METADATA_KEY_RESOLVES, validate_event  # noqa: E402
from smm_schema import EVENT_ID_RE  # noqa: E402

_REFS_SUFFIX_RE = re.compile(r"\[refs:\s*([^\]]+)\]\s*$")
_SPLIT_RE = re.compile(r"[,\s]+")


def _extract_refs(content: str) -> tuple[str, list[str]]:
    """Return (cleaned_content, valid_event_ids).

    Strips any trailing `[refs: ...]` block and returns the 12-hex ids
    (matching `smm_schema.EVENT_ID_RE`). Malformed tokens are silently
    dropped so typos don't break adoption.
    """
    match = _REFS_SUFFIX_RE.search(content)
    if not match:
        return content, []
    cleaned = content[: match.start()].rstrip()
    tokens = _SPLIT_RE.split(match.group(1).strip())
    ids = [t for t in tokens if EVENT_ID_RE.match(t)]
    return cleaned, ids


def _build_metadata(ids: list[str], disposition: str | None) -> dict | None:
    """Build metadata dict, or None if nothing to set."""
    meta: dict = {}
    if ids:
        meta[METADATA_KEY_RESOLVES] = ids
    if disposition:
        meta["disposition"] = disposition
    return meta or None


def run(
    action: str,
    smm_dir: Path,
    content: str,
    topic: str | None = None,
    event_id: str | None = None,
) -> str:
    """Append the event and return its id.

    Retro Try actions: "adopt" | "defer" | "drop" (content-based).
    Triage actions: "triage-adopt" | "triage-defer" | "triage-drop"
    (event-id-based).
    """
    clean_content, ids = _extract_refs(content)

    match action:
        case "adopt":
            metadata = _build_metadata(ids, None)
            kwargs: dict = {"topic": topic}
            if metadata:
                kwargs["metadata"] = metadata
            event = _common.make_event(
                "decision",
                "xp-work-selection",
                clean_content,
                **kwargs,
            )
        case "defer" | "drop":
            disposition = "deferred" if action == "defer" else "dropped"
            event = _common.make_event(
                "status",
                "xp-work-selection",
                clean_content,
                working_on=[],
                metadata=_build_metadata(ids, disposition),
            )
        case "triage-adopt" | "triage-defer" | "triage-drop":
            if event_id is None:
                raise ValueError(f"{action} requires --event-id")
            if not EVENT_ID_RE.match(event_id):
                raise ValueError(f"Invalid event ID format: {event_id}")
            _triage_dispositions = {
                "triage-adopt": "adopted",
                "triage-defer": "deferred",
                "triage-drop": "dropped",
            }
            disposition = _triage_dispositions[action]
            resolve_ids = [event_id] if disposition != "deferred" else []
            event = _common.make_event(
                "status",
                "xp-work-selection",
                f"Triage: {disposition} {event_id[:8]}",
                working_on=[],
                metadata=_build_metadata(resolve_ids, disposition),
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
