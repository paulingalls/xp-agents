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

import close_window
import concern_relevance
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


def _provably_out_of_window(line: str, floor: str | None) -> bool:
    """True only when *line* is an unparseable JSONL line with a
    recoverable "ts" substring that lexicographically precedes *floor*
    — i.e. positive evidence the line predates the scoped window, safe
    to exclude from the fail-closed floor. *floor* is the window's
    effective lower bound, which count-concerns resolves through
    close_window rather than passing its --since-ts straight through.

    Requires the line to still start with '{' (looks like an attempted
    JSON object) before trusting the extraction — the dominant
    real-world corruption mode is a truncated atomic write of an
    otherwise well-formed event, not adversarial garbage, so a
    recognizable "ts" field on an otherwise-object-shaped line is a
    trustworthy signal. Returns False (never excludes) whenever the
    floor is unset or no ts can be extracted, so genuinely unscopable
    corruption stays on the fail-closed floor.
    """
    if not floor or not line.startswith("{"):
        return False
    match = _EMBEDDED_TS_RE.search(line)
    if not match:
        return False
    return match.group(1) < floor


def _floor_count(bad_lines: list[str], floor: str | None) -> tuple[int, int]:
    """Split unparseable lines into (still-counted, provably-excluded).

    Returns (in_scope, excluded) where in_scope + excluded == len(bad_lines).
    """
    excluded = sum(1 for line in bad_lines if _provably_out_of_window(line, floor))
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


def _repo_root(spec: str | None) -> Path | None:
    """Where recorded concern paths are resolved to prove they EXIST.

    `--repo-root` when given, else the process cwd — the close gate pipes
    `git diff --name-only` from the repo it is closing, so its cwd is that
    repo (or a worktree of it, where the same tracked paths resolve).

    None when cwd itself cannot be read (a deleted working directory raises
    OSError). The caller then skips the narrowing entirely and counts
    everything: with no root, no path can be proved present, and a rule that
    cannot see must not drop anything.
    """
    if spec:
        return Path(spec)
    try:
        return Path.cwd()
    except OSError:
        return None


def _cmd_count_concerns(args: argparse.Namespace) -> int:
    """Count OPEN type==concern events filtered by severity, cycle-id, since-ts.

    "Open" means not resolved — via metadata.resolves or the WEAK
    references cascade (see resolution.compute_resolutions). A concern
    filed and later fixed-and-linked must stop counting, or a resolved
    finding blocks the close gate forever.

    How WIDE the count looks is close_window's decision, taken from the
    gated cycle's own close_mode rather than from the flags: an
    ENCLOSING close (sprint/plan/free) is bounded by the sprint start,
    so a concern an earlier story-close left open still counts against
    the merge gate that exists to catch it. A `story` close keeps the
    narrow window (concern f106bf044ded / decision efed0cb00c62).

    Always exits 0 (missing file → 0) so callers can `$(...)` capture
    without exit-code branching. A malformed line is COUNTED (fail
    closed) — only an ABSENT events.jsonl returns 0; a hidden high
    concern must never silently lower the count — UNLESS a ts
    substring can be recovered from the raw line and it provably
    precedes the window floor, in which case it is excluded (see
    _provably_out_of_window; concern a11e9132e5bc).

    With --cycle-id AND a non-empty --diff-paths, an UNTAGGED concern that is
    provably about code this close does not touch is excluded (see
    concern_relevance.provably_outside_diff; concern 3542ad2915df). Without both
    flags the count is byte-identical to the un-scoped one — the narrowing is
    opt-in.

    Sync pointer: story-close/free-close auto-merge conditions 1 & 2
    (SKILL.md) rely on this fail-closed behavior.
    """
    # Read --diff-paths BEFORE the existence check so a `git diff | ...` producer
    # is never left writing into an unread pipe on the missing-SMM path.
    diff_paths = concern_relevance.load_diff_paths(args.diff_paths)
    repo_root = _repo_root(args.repo_root)
    if diff_paths and repo_root is None:
        print(
            "count-concerns: no repo root is readable (cwd is gone and "
            "--repo-root was not given); counting every concern in scope, "
            "exactly as if --diff-paths were absent (fail closed)",
            file=sys.stderr,
        )
    if args.diff_paths and not diff_paths:
        print(
            f"count-concerns: --diff-paths {args.diff_paths} was empty or "
            "unreadable; counting every concern in scope, exactly as if the "
            "flag were absent (fail closed)",
            file=sys.stderr,
        )
    events_path = Path(args.smm_dir) / "events.jsonl"
    if not events_path.exists():
        print(0)
        return 0
    raw_text = events_path.read_text()
    events, skipped = parse_jsonl(raw_text)
    # ONE window for the tag rule and BOTH floor sites — the events filter below
    # and the corrupt-line floor. Two spellings of one rule is the old drift.
    window = close_window.resolve(
        events, Path(args.smm_dir), cycle_id=args.cycle_id, since_ts=args.since_ts
    )
    close_window.report(window, "count-concerns")
    resolved_ids = compute_resolutions(events)["resolved_concern_ids"]
    count = 0
    for event in events:
        if event.get("type") != EVENT_TYPE_CONCERN:
            continue
        if args.severity and event.get("severity") != args.severity:
            continue
        meta = event.get("metadata", {})
        tag = meta.get(METADATA_KEY_CLOSE_CYCLE_ID)
        if window.excludes_tag(tag):
            continue
        if window.floor and event.get("ts", "") < window.floor:
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
        # Second untagged carve-out, same shape as the one above: exclude by
        # PROVABLE IRRELEVANCE, never by absence of a tag. The invariant —
        # excluded-from-scoped-gate IFF the concern names files that all EXIST
        # in the working tree and none of which intersect the close diff, i.e.
        # it is provably about OTHER code that is present and untouched
        # (concern 3542ad2915df; story-003's clean close was pushed to
        # abort-recommended by 964426f13819, an unrelated open lock defect in a
        # sibling's domain recorded in the same --since-ts window).
        #
        # Do NOT collapse this conjunction. Each clause is a fail-closed
        # default, and `diff_paths` being non-empty is the load-bearing one:
        # against an empty set provably_outside_diff is vacuously true for
        # every concern with files, so dropping that clause turns the whole
        # gate off whenever the caller's `git diff` came back empty.
        if (
            args.cycle_id
            and diff_paths
            and repo_root is not None
            and tag is None
            and concern_relevance.provably_outside_diff(event, diff_paths, repo_root)
        ):
            continue
        count += 1
    # Only re-walk the raw text to recover the exact unparseable lines when
    # parse_jsonl actually skipped some — the healthy case (skipped == 0) must
    # not pay a second full parse of the whole log.
    bad_lines = _skipped_lines(raw_text) if skipped else []
    in_scope, excluded = _floor_count(bad_lines, window.floor)
    if excluded:
        print(
            f"count-concerns: excluded {excluded} unparseable line(s) in "
            f"{events_path} with an embedded ts older than the window floor "
            f"{window.floor} (provably out of scope)",
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
        help="Filter by metadata.close_cycle_id, and the key that sets the "
        "window width — this cycle's close_started names the close MODE. A story "
        "close excludes every differently-tagged event, so a concurrent "
        "close-cycle's do not leak in; an ENCLOSING close excludes a tag only "
        "when its close is provably from an earlier sprint. An event WITHOUT the "
        "key always counts (fails closed) — pair with --diff-paths to drop the "
        "untagged ones provably about code this close does not touch.",
    )
    cc_p.add_argument(
        "--diff-paths",
        default=None,
        metavar="PATH",
        help="File of NUL- or newline-separated repo-relative paths in the "
        "close diff (`-` reads stdin) — e.g. "
        "`git diff --no-renames --name-only -z <review-base>...HEAD`. Use `-z`: "
        'without it git QUOTES any path holding non-ASCII bytes, `"`, `\\` or a '
        "control byte such as a newline, "
        "and a quoted path matches no `files` entry, so a concern about a file "
        "this close touched reads as provably-elsewhere and is dropped. "
        "Only meaningful WITH --cycle-id: an untagged concern whose `files` all "
        "EXIST and all lie outside the diff is then excluded. Empty or "
        "unreadable behaves exactly as if absent (counts everything) and notes "
        "so on stderr.",
    )
    cc_p.add_argument(
        "--repo-root",
        default=None,
        metavar="PATH",
        help="Where a concern's recorded paths are resolved to prove they "
        "exist (default: cwd). A path that does not exist is NOT proof of "
        "irrelevance — a review naming a file nobody wrote (a missing test) "
        "must still count. Only meaningful WITH --cycle-id and --diff-paths.",
    )
    cc_p.add_argument(
        "--since-ts",
        default=None,
        help="ISO 8601 timestamp; events with ts < this are excluded — but ONLY "
        "when --cycle-id names a `story` close. An enclosing close is bounded by "
        "its sprint's start instead, an unreadable mode by nothing at all; both "
        "say so on stderr.",
    )
