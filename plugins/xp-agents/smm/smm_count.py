#!/usr/bin/env python3
"""Count subcommands for smm_cli: count-classifications, count-concerns.

Extracted from smm_cli.py to keep that file under the 500-line cap.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from append_validation import parse_jsonl
from event_metadata import CONCERN_ACTION_TRANSIENT_TEST
from event_schema import (
    EVENT_TYPE_CONCERN,
    METADATA_KEY_CLOSE_CYCLE_ID,
    STATUS_ACTION_CONCERN_CLASSIFY,
    VALID_SEVERITIES,
)
from resolution import compute_resolutions

# Best-effort recovery for concern a11e9132e5bc / debt 7e8219afe702: an
# unparseable line has no reliable ts to scope by, so it must stay on
# the fail-closed floor (counted) by default — but ONE ancient corrupt
# line should not permanently force every future --since-ts-scoped
# close to count non-zero. If a "ts" substring can still be recovered
# from the raw (unparseable) line and it lexicographically precedes
# --since-ts, the line is PROVABLY out of the scoped window and is
# excluded. This only ever narrows the floor for lines with positive
# evidence of being out of scope; a line with no extractable ts, or an
# extracted ts inside the window, still counts (floor unchanged).
_EMBEDDED_TS_RE = re.compile(
    r'"ts"\s*:\s*"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})"'
)


def _skipped_lines(raw: str) -> list[str]:
    """Re-walk raw JSONL text to recover the exact lines parse_jsonl
    counted as unparseable (malformed JSON or a non-dict value), so
    their raw text is available for best-effort ts extraction.

    Mirrors parse_jsonl's skip criteria exactly (blank lines are not
    unparseable; only malformed JSON or non-dict values are) so
    len(_skipped_lines(raw)) always equals parse_jsonl's skipped count.
    Duplicated here rather than changing parse_jsonl's return shape,
    since every other events.jsonl reader (materialize.py, compact.py,
    …) only needs the count, not the raw text.
    """
    bad: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                bad.append(line)
        except json.JSONDecodeError:
            bad.append(line)
    return bad


def _provably_out_of_window(line: str, since_ts: str | None) -> bool:
    """True only when *line* is an unparseable JSONL line with a
    recoverable "ts" substring that lexicographically precedes
    *since_ts* — i.e. positive evidence the line predates the scoped
    window, safe to exclude from the fail-closed floor.

    Requires the line to still start with '{' (looks like an attempted
    JSON object) before trusting the extraction — the dominant
    real-world corruption mode is a truncated atomic write of an
    otherwise well-formed event, not adversarial garbage, so a
    recognizable "ts" field on an otherwise-object-shaped line is a
    trustworthy signal. Returns False (never excludes) whenever
    since_ts is unset or no ts can be extracted, so genuinely
    unscopable corruption stays on the fail-closed floor.
    """
    if not since_ts or not line.startswith("{"):
        return False
    match = _EMBEDDED_TS_RE.search(line)
    if not match:
        return False
    return match.group(1) < since_ts


def _floor_count(bad_lines: list[str], since_ts: str | None) -> tuple[int, int]:
    """Split unparseable lines into (still-counted, provably-excluded).

    Returns (in_scope, excluded) where in_scope + excluded == len(bad_lines).
    """
    excluded = sum(1 for line in bad_lines if _provably_out_of_window(line, since_ts))
    return len(bad_lines) - excluded, excluded


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
    returns 0. A malformed line is COUNTED (fail closed), not skipped
    — only an ABSENT events.jsonl returns 0 — UNLESS a ts substring can
    be recovered from the raw line and it provably precedes
    --since-ts, in which case it is excluded (see
    _provably_out_of_window; concern a11e9132e5bc). The "absent → 0"
    semantics let the auto-merge gate's `ASK_COUNT=$(...)` invocation
    work without exit-code branching, mirroring system_context_cli.py
    get-stack-field's "absent → empty" pattern.

    Used by story-close + free-close auto-merge override condition 1
    to verify Step 5c queued zero ask-user items via structured
    metadata instead of regex over LLM-authored content. The --category
    filter (per concern 28f5e1b919d6) lets free-close also block
    auto-merge when any design_decision finding was classified, even
    if routed to fix.

    Sync pointer: story-close/free-close auto-merge conditions 1 & 2
    (SKILL.md) rely on this fail-closed behavior — a corrupt line must
    never silently lower the count.
    """
    events_path = Path(args.smm_dir) / "events.jsonl"
    if not events_path.exists():
        print(0)
        return 0
    # Delegate to the canonical JSONL parser used by all events.jsonl
    # readers (materialize.py, compact.py, …) — handles blank lines,
    # malformed JSON, and non-dict values uniformly.
    raw_text = events_path.read_text()
    events, skipped = parse_jsonl(raw_text)
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
    # Only re-walk the raw text to recover the exact unparseable lines when
    # parse_jsonl actually skipped some — the healthy case (skipped == 0) must
    # not pay a second full parse of the whole log.
    bad_lines = _skipped_lines(raw_text) if skipped else []
    in_scope, excluded = _floor_count(bad_lines, args.since_ts)
    if excluded:
        print(
            f"count-classifications: excluded {excluded} unparseable line(s) "
            f"in {events_path} with an embedded ts older than --since-ts "
            f"{args.since_ts} (provably out of scope)",
            file=sys.stderr,
        )
    if in_scope:
        print(
            f"count-classifications: {in_scope} unparseable line(s) in "
            f"{events_path}; counting each as a potential concern "
            "(fail closed)",
            file=sys.stderr,
        )
        count += in_scope
    print(count)
    return 0


def _is_transient_test_concern(event: dict) -> bool:
    """True for a hook-raised test-failure concern — the one transient class.

    Provenance, not wording: `bash_failure` and `bash_post_tool` stamp
    CONCERN_ACTION_TRANSIENT_TEST on the concerns that auto-resolve on the next
    green run. Nothing else sets it, so an LLM-authored concern can never
    impersonate the class no matter how it is phrased.

    There is deliberately NO content fallback for events written before the
    marker shipped. A fallback would have to ask the wording again, which is the
    exact fail-open being closed — an unmarked reviewer Block phrased "test
    command failed" would keep being dropped. Unmarked therefore means counted,
    in both directions: the worst case is a pre-marker transient concern
    counting once against a close that starts before the next green run
    clears it, which fails CLOSED (a spurious abort the operator can see and
    override) rather than OPEN (a silent merge over a real block).
    """
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return metadata.get("action") == CONCERN_ACTION_TRANSIENT_TEST


def _cmd_count_concerns(args: argparse.Namespace) -> int:
    """Count OPEN type==concern events filtered by severity, cycle-id, since-ts.

    "Open" means not resolved — via metadata.resolves or the WEAK
    references cascade (see resolution.compute_resolutions). A concern
    filed and later fixed-and-linked must stop counting, or a resolved
    finding blocks the close gate forever.

    Always exits 0 (missing file → 0) so callers can `$(...)` capture
    without exit-code branching. A malformed line is COUNTED (fail
    closed) — only an ABSENT events.jsonl returns 0; a hidden high
    concern must never silently lower the count — UNLESS a ts
    substring can be recovered from the raw line and it provably
    precedes --since-ts, in which case it is excluded (see
    _provably_out_of_window; concern a11e9132e5bc).

    Sync pointer: story-close/free-close auto-merge conditions 1 & 2
    (SKILL.md) rely on this fail-closed behavior.
    """
    events_path = Path(args.smm_dir) / "events.jsonl"
    if not events_path.exists():
        print(0)
        return 0
    raw_text = events_path.read_text()
    events, skipped = parse_jsonl(raw_text)
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
        # Transient TDD test-failure concerns (bash_post_tool + bash_failure) carry
        # no close_cycle_id and auto-resolve on a green run. In a SCOPED close-gate
        # count (--cycle-id set) a CONCURRENT teammate's still-red one leaks in and
        # false-aborts a sibling's clean close (concern f995656dba80).
        # Excluded by PROVENANCE — see _is_transient_test_concern. The
        # invariant still holds: excluded-from-scoped-gate IFF
        # auto-resolves-on-green, since the marker is stamped by exactly
        # the producers whose concerns bash_post_tool clears on green.
        if args.cycle_id and tag is None and _is_transient_test_concern(event):
            continue
        count += 1
    # Only re-walk the raw text to recover the exact unparseable lines when
    # parse_jsonl actually skipped some — the healthy case (skipped == 0) must
    # not pay a second full parse of the whole log.
    bad_lines = _skipped_lines(raw_text) if skipped else []
    in_scope, excluded = _floor_count(bad_lines, args.since_ts)
    if excluded:
        print(
            f"count-concerns: excluded {excluded} unparseable line(s) in "
            f"{events_path} with an embedded ts older than --since-ts "
            f"{args.since_ts} (provably out of scope)",
            file=sys.stderr,
        )
    if in_scope:
        print(
            f"count-concerns: {in_scope} unparseable line(s) in {events_path}; "
            "counting each as a potential concern (fail closed)",
            file=sys.stderr,
        )
        count += in_scope
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
