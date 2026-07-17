#!/usr/bin/env python3
"""Count subcommands for smm_cli: count-classifications, count-concerns.

Extracted from smm_cli.py to keep that file under the 500-line cap.
"""

import argparse
from pathlib import Path

from append_validation import parse_jsonl
from event_schema import (
    EVENT_TYPE_CONCERN,
    METADATA_KEY_CLOSE_CYCLE_ID,
    STATUS_ACTION_CONCERN_CLASSIFY,
    VALID_SEVERITIES,
)
from resolution import compute_resolutions


def _cmd_count_classifications(args: argparse.Namespace) -> int:
    """Count concern_classify events matching --route and/or --category,
    optionally bounded by --since-ts (ISO 8601 timestamp).

    Filters each event by:
      - metadata.action == "concern_classify"
      - metadata.route == args.route (when provided)
      - metadata.category == args.category (when provided)
      - metadata.close_cycle_id == args.cycle_id (when provided — an
        event WITHOUT the key is counted; only an event tagged with a
        DIFFERENT cycle id is excluded)
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
        tag = meta.get(METADATA_KEY_CLOSE_CYCLE_ID)
        if args.cycle_id and tag is not None and tag != args.cycle_id:
            continue
        if args.since_ts and event.get("ts", "") < args.since_ts:
            continue
        count += 1
    print(count)
    return 0


def _cmd_count_concerns(args: argparse.Namespace) -> int:
    """Count OPEN type==concern events filtered by severity, cycle-id, since-ts.

    "Open" means not resolved — via metadata.resolves or the WEAK
    references cascade (see resolution.compute_resolutions). A concern
    filed and later fixed-and-linked must stop counting, or a resolved
    finding blocks the close gate forever.

    Always exits 0 (missing file / malformed lines → 0) so callers can
    `$(...)` capture without exit-code branching.
    """
    events_path = Path(args.smm_dir) / "events.jsonl"
    if not events_path.exists():
        print(0)
        return 0
    events, _skipped = parse_jsonl(events_path.read_text())
    resolved_ids = compute_resolutions(events)["resolved_concern_ids"]
    count = 0
    for event in events:
        if event.get("type") != EVENT_TYPE_CONCERN:
            continue
        if args.severity and event.get("severity") != args.severity:
            continue
        meta = event.get("metadata", {})
        tag = meta.get(METADATA_KEY_CLOSE_CYCLE_ID)
        if args.cycle_id and tag is not None and tag != args.cycle_id:
            continue
        if args.since_ts and event.get("ts", "") < args.since_ts:
            continue
        if event.get("id", "") in resolved_ids:
            continue
        count += 1
    print(count)
    return 0


def register_parsers(sub: argparse._SubParsersAction) -> None:
    """Register count-classifications and count-concerns subparsers."""
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
        "CLOSE_CYCLE_ID); excludes events tagged with a DIFFERENT cycle id, "
        "so a concurrent close-cycle's tagged events do not leak in. An "
        "event WITHOUT the key is counted (fails closed rather than dropping "
        "it) — pair with --since-ts to bound untagged events.",
    )
    count_p.add_argument(
        "--since-ts",
        default=None,
        help="ISO 8601 timestamp; events with ts < this are excluded",
    )

    cc_p = sub.add_parser(
        "count-concerns",
        help="Count OPEN concern events filtered by severity + cycle-id + since-ts",
    )
    cc_p.add_argument(
        "--severity",
        default=None,
        choices=sorted(VALID_SEVERITIES),
        help="Filter by severity; omit to count all severities. "
        "choices= rejects typos so a silent zero never defeats the gate.",
    )
    cc_p.add_argument(
        "--cycle-id",
        default=None,
        help="Filter by metadata.close_cycle_id; excludes events tagged "
        "with a DIFFERENT cycle id, so a concurrent close-cycle's tagged "
        "events do not leak in. An event WITHOUT the key is counted (fails "
        "closed rather than dropping it) — pair with --since-ts to bound "
        "untagged events.",
    )
    cc_p.add_argument(
        "--since-ts",
        default=None,
        help="ISO 8601 timestamp; events with ts < this are excluded",
    )
