#!/usr/bin/env python3
"""CLI for SMM operations.

Thin wrapper over smm_store.py for shell scripts and skills.
Python scripts may import the rendering functions directly.

Also provides extract_pillar / extract_pillars for subsetting
(used by subagent_start.py for Explore-tier injection).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import marker_names
import smm_store
from append_validation import parse_jsonl
from event_schema import STATUS_ACTION_CONCERN_CLASSIFY
from smm_schema import PILLAR_RISKS, PILLARS

_PILLAR_TITLES = {
    "intent": "Intent",
    "constraints": "Constraints",
    "risks": "Risks",
    "wisdom": "Wisdom",
}


def _render_entry(entry: dict, show_id: bool = False) -> str:
    """Render a single pillar entry as a markdown bullet."""
    content = entry.get("content", "")
    if show_id:
        return f"- {content} [{entry.get('id', '')}]"
    return f"- {content}"


def _render_pillar_section(entries: list, pillar: str) -> str:
    """Render one pillar as a markdown section."""
    title = _PILLAR_TITLES.get(pillar, pillar.title())
    show_id = pillar == PILLAR_RISKS
    lines = [f"## {title}"]
    for entry in entries:
        lines.append(_render_entry(entry, show_id=show_id))
    return "\n".join(lines)


def render_markdown(smm: dict) -> str:
    """Render a full curated SMM as markdown.

    Args:
        smm: Parsed SMM dict with intent/constraints/risks/wisdom pillars.

    Returns:
        Complete markdown string with header and four pillar sections.
    """
    parts = [marker_names.RENDER_SMM_SIGNATURE, ""]

    for pillar in PILLARS:
        entries = smm.get(pillar, [])
        parts.append(_render_pillar_section(entries, pillar))
        parts.append("")

    return "\n".join(parts)


def extract_pillar(smm: dict, pillar: str) -> str:
    """Extract a single pillar section as markdown.

    Returns empty string if the pillar name is not recognized.
    """
    if pillar not in _PILLAR_TITLES:
        return ""
    entries = smm.get(pillar, [])
    return _render_pillar_section(entries, pillar) + "\n"


def extract_pillars(smm: dict, pillars: set[str]) -> str:
    """Extract multiple pillar sections, concatenated under a header.

    Used by subagent_start.py for Explore-tier injection (Intent +
    Constraints only).
    """
    parts = []
    for pillar in PILLARS:
        if pillar in pillars:
            parts.append(extract_pillar(smm, pillar))

    if not parts:
        return ""
    return f"{marker_names.RENDER_SMM_SIGNATURE}\n\n" + "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def _cmd_render(args: argparse.Namespace) -> int:
    """Render full SMM as markdown to stdout."""
    smm = smm_store.load_smm(args.smm_dir)
    print(render_markdown(smm))
    return 0


def _cmd_section(args: argparse.Namespace) -> int:
    smm = smm_store.load_smm(args.smm_dir)
    print(extract_pillar(smm, args.name.lower()))
    return 0


def _cmd_has_section(args: argparse.Namespace) -> int:
    smm = smm_store.load_smm(args.smm_dir)
    name = args.name.lower()
    entries = smm.get(name, [])
    return 0 if entries else 1


def _cmd_complete_curation(args: argparse.Namespace) -> int:
    complete_curation(args.smm_dir)
    return 0


def _cmd_add_item(args: argparse.Namespace) -> int:
    content = sys.stdin.read().strip()
    if not content:
        print("Error: no content provided on stdin", file=sys.stderr)
        return 1
    try:
        uid = smm_store.add_item(
            args.smm_dir,
            args.pillar,
            content,
            type=args.type,
            topic=args.topic,
            severity=args.severity,
            source=args.source or "curated",
            source_event_id=args.source_event_id,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(uid)
    return 0


def _cmd_update_item(args: argparse.Namespace) -> int:
    content = sys.stdin.read().strip() or None
    try:
        smm_store.update_item(
            args.smm_dir,
            args.item_id,
            content=content,
            type=args.type,
            topic=args.topic,
            severity=args.severity,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_promote_event(args: argparse.Namespace) -> int:
    try:
        uid = smm_store.promote_event(
            args.smm_dir,
            args.event_id,
            pillar=args.pillar,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(uid)
    return 0


def _cmd_remove_item(args: argparse.Namespace) -> int:
    try:
        smm_store.remove_item(args.smm_dir, args.item_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_count_classifications(args: argparse.Namespace) -> int:
    """Count concern_classify events matching --route and/or --category,
    optionally bounded by --since-ts (ISO 8601 timestamp).

    Filters each event by:
      - metadata.action == "concern_classify"
      - metadata.route == args.route (when provided)
      - metadata.category == args.category (when provided)
      - metadata.close_cycle_id == args.cycle_id (when provided —
        events without the key never match, so pre-cycle-id events
        don't leak into a scoped count)
      - ts >= args.since_ts (lexicographic ISO comparison; safe because
        all event ts values use the same fixed-width "YYYY-MM-DDTHH:MM:SS+00:00"
        shape per append.sh)

    Always exits 0 — empty event log returns 0, missing events.jsonl
    returns 0, malformed lines are skipped. The "absent → 0" semantics
    let the auto-merge gate's `ASK_COUNT=$(...)` invocation work
    without exit-code branching, mirroring system_context_cli.py
    get-stack-field's "absent → empty" pattern.

    Used by story-close + free-close auto-merge override condition 1
    to verify Step 5c queued zero ask-user items via structured
    metadata instead of regex over LLM-authored content. The --category
    filter (per concern 28f5e1b919d6) lets free-close also block
    auto-merge when any design_decision finding was classified, even
    if routed to fix.
    """
    events_path = Path(args.smm_dir) / "events.jsonl"
    if not events_path.exists():
        print(0)
        return 0
    # Delegate to the canonical JSONL parser used by all events.jsonl
    # readers (materialize.py, compact.py, …) — handles blank lines,
    # malformed JSON, and non-dict values uniformly.
    events, _skipped = parse_jsonl(events_path.read_text())
    count = 0
    for event in events:
        meta = event.get("metadata", {})
        if meta.get("action") != STATUS_ACTION_CONCERN_CLASSIFY:
            continue
        if args.route and meta.get("route") != args.route:
            continue
        if args.category and meta.get("category") != args.category:
            continue
        if args.cycle_id and meta.get("close_cycle_id") != args.cycle_id:
            continue
        if args.since_ts and event.get("ts", "") < args.since_ts:
            continue
        count += 1
    print(count)
    return 0


def _cmd_get_event(args: argparse.Namespace) -> int:
    try:
        _, event = smm_store.lookup_event(args.smm_dir, args.event_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(event, indent=2))
    return 0


def _cmd_save(args: argparse.Namespace) -> int:
    content = sys.stdin.read()
    try:
        save(content, smm_dir=args.smm_dir)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Library function for save (callable from Python or CLI)
# ---------------------------------------------------------------------------


def complete_curation(smm_dir: Path) -> None:
    """Finalize curation: run compaction, then advance watermark.

    Always advances the watermark to the current event count so the
    next compaction cycle considers all curated events as eligible.
    Uses compact's retained count when available to avoid a second
    events.jsonl read.
    """
    import contextlib

    import compact
    import materialize

    result = None
    with contextlib.suppress(OSError, ValueError):
        result = compact.compact_after_curation(smm_dir)

    if result and "retained" in result:
        event_count = result["retained"]
    else:
        events, _ = materialize.parse_events(smm_dir)
        event_count = len(events)

    materialize.write_curation_watermark(smm_dir, event_count, "xp-housekeeper")


def save(content: str, *, smm_dir: Path) -> None:
    """Parse JSON, validate, write, update watermark, compact.

    Raises:
        json.JSONDecodeError: If content is not valid JSON.
        ValueError: If content fails SMM schema validation.
    """
    data = json.loads(content)
    smm_store.save_smm(smm_dir, data)
    complete_curation(smm_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SMM CLI",
        epilog=(
            "Examples:\n"
            '  echo "text" | smm_cli.py --smm-dir DIR add-item'
            " constraints --type convention --topic name\n"
            "  smm_cli.py --smm-dir DIR get-event abc123\n"
            "  smm_cli.py --smm-dir DIR render\n"
            "  smm_cli.py --smm-dir DIR remove-item ITEM_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--smm-dir", type=Path, required=True, help="SMM directory path"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("render", help="Render full SMM as markdown")

    sec_p = sub.add_parser("section", help="Render a single pillar")
    sec_p.add_argument("name", help="Pillar name (intent/constraints/risks/wisdom)")

    has_p = sub.add_parser("has-section", help="Check if a pillar has entries")
    has_p.add_argument("name", help="Pillar name (intent/constraints/risks/wisdom)")

    sub.add_parser("save", help="Save SMM from stdin JSON")

    sub.add_parser("complete-curation", help="Finalize curation (watermark + compact)")

    add_p = sub.add_parser("add-item", help="Add item to a pillar (content from stdin)")
    add_p.add_argument("pillar", choices=list(PILLARS), help="Target pillar")
    add_p.add_argument("--type", default=None, help="Entry type")
    add_p.add_argument("--topic", default=None, help="Topic (constraints)")
    add_p.add_argument("--severity", default=None, help="Severity (risks)")
    add_p.add_argument("--source", default=None, help="Source (default: curated)")
    add_p.add_argument("--source-event-id", default=None, help="Source event UUID")

    upd_p = sub.add_parser("update-item", help="Update item fields")
    upd_p.add_argument("item_id", help="Item UUID to update")
    upd_p.add_argument("--type", default=None, help="New entry type")
    upd_p.add_argument("--topic", default=None, help="New topic")
    upd_p.add_argument("--severity", default=None, help="New severity")

    rm_p = sub.add_parser("remove-item", help="Remove item by ID")
    rm_p.add_argument("item_id", help="Item UUID to remove")

    get_p = sub.add_parser("get-event", help="Print event by ID or prefix")
    get_p.add_argument("event_id", help="Event UUID or prefix")

    count_p = sub.add_parser(
        "count-classifications",
        help="Count concern_classify events filtered by "
        "route + category + cycle-id + since-ts",
    )
    count_p.add_argument(
        "--route",
        choices=["fix", "ask"],
        default=None,
        help="Filter by metadata.route (omit to count all routes)",
    )
    count_p.add_argument(
        "--category",
        default=None,
        help="Filter by metadata.category (e.g. design_decision); "
        "omit to count all categories",
    )
    count_p.add_argument(
        "--cycle-id",
        default=None,
        help="Filter by metadata.close_cycle_id (12-hex from preload "
        "CLOSE_CYCLE_ID); strict close-cycle scoping that prevents "
        "concurrent-close leakage. Events without the key never match.",
    )
    count_p.add_argument(
        "--since-ts",
        default=None,
        help="ISO 8601 timestamp; events with ts < this are excluded",
    )

    prm_p = sub.add_parser("promote-event", help="Promote event to SMM")
    prm_p.add_argument("event_id", help="Event UUID or prefix")
    prm_p.add_argument(
        "--pillar",
        default=None,
        choices=list(PILLARS),
        help="Target pillar (default: derived from event type)",
    )

    args = parser.parse_args()

    dispatch = {
        "render": _cmd_render,
        "section": _cmd_section,
        "has-section": _cmd_has_section,
        "save": _cmd_save,
        "complete-curation": _cmd_complete_curation,
        "add-item": _cmd_add_item,
        "update-item": _cmd_update_item,
        "remove-item": _cmd_remove_item,
        "get-event": _cmd_get_event,
        "count-classifications": _cmd_count_classifications,
        "promote-event": _cmd_promote_event,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
