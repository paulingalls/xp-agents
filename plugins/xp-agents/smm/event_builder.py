#!/usr/bin/env python3
"""Event builder: CLI argument parsing and event dict construction.

Converts argparse.Namespace into event dicts. No I/O, no validation
(that's event_schema.validate_event's job).

Extracted from _append_impl.py for module size management.
"""

import argparse
import json
import re
import secrets
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from event_metadata import METADATA_KEY_RESOLVES, is_closing
from event_schema import CONTENT_BUDGETS, MAX_JSON_ARG_SIZE, VALID_TYPES
from smm_schema import EVENT_ID_RE

# The top-level WEAK link field. Named here — beside the two merge helpers and
# the extractor that write it — so producer and consumer can't drift on the
# spelling, the same way METADATA_KEY_* pins the metadata keys.
REFERENCES_KEY = "references"

_REFS_SUFFIX_RE = re.compile(r"\[refs:\s*([^\]]+)\]\s*$")
_REFS_SPLIT_RE = re.compile(r"[,\s]+")

_URL_RE = re.compile(r"https?://\S+")
# Intentionally NOT reusing lint_check._CODE_EXTENSIONS at runtime: that's a
# Python frozenset; this regex needs a literal alternation. Both lists are
# extension catalogs and should evolve together — when adding a language to
# _LINTER_EXTENSIONS, add its primary source extensions here too. Keeping the
# alternation broad (Python, JS/TS, Rust, Go, Ruby, C/C++, Java, Kotlin, PHP,
# Dart, Elixir, C#, Swift, plus prose/config) preserves the recall-biased
# extraction across xp-agents users — narrowing to one language's set would
# silence the very signals the probe was built to surface.
# `(?<![\w/])` (not `\b`) at the start lets leading-slash absolute paths
# (`/abs/path/foo.py`) capture intact rather than dropping the `/` and
# misresolving relative to cwd downstream.
_FILE_PATTERN_RE = re.compile(
    r"(?<![\w/])([\w./-]+\.(?:py|pyi|ipynb"
    r"|js|ts|jsx|tsx|mjs|cjs|vue"
    r"|rs|go|rb"
    r"|c|cpp|cc|cxx|h|hpp"
    r"|java|kt|kts|php|dart|ex|exs|cs|swift"
    r"|md|sh|json|yaml|yml|toml|jsonl))\b"
)


def extract_files_from_content(content: str) -> list[str]:
    """Find path-shaped tokens in content; recall-biased (probe filters later).

    Strips http(s) URLs first so paths inside URL tails don't match.
    Dedupes, preserves first-seen order.
    """
    cleaned = _URL_RE.sub("", content)
    seen: set[str] = set()
    result: list[str] = []
    for match in _FILE_PATTERN_RE.finditer(cleaned):
        path = match.group(1)
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def generate_id() -> str:
    """12-char hex ID for events and SMM entries."""
    return secrets.token_hex(6)


def _merge_ids(container: dict, key: str, ids: Iterable[str]) -> None:
    """Append `ids` into container[key], preserving order and skipping
    duplicates. Defensive copy avoids mutating a list the caller may share
    across events. Mutates container in place.
    """
    merged = list(container.get(key, []))
    for tid in ids:
        if tid not in merged:
            merged.append(tid)
    container[key] = merged


def merge_resolves(event: dict, ids: Iterable[str]) -> None:
    """Union `ids` into the STRONG closure link, event.metadata.resolves."""
    _merge_ids(event.setdefault("metadata", {}), METADATA_KEY_RESOLVES, ids)


def merge_references(event: dict, ids: Iterable[str]) -> None:
    """Union `ids` into the WEAK link, the top-level `references` list."""
    _merge_ids(event, REFERENCES_KEY, ids)


def extract_refs_suffix(event: dict) -> None:
    """Strip a trailing `[refs: id1, id2]` suffix from event["content"] and
    union the extracted 12-hex IDs into the link field the event's own
    evidence warrants:

      - closing event (terminal disposition, per `is_closing`) →
        metadata.resolves, which marks the target RESOLVED
      - every other event → the top-level `references` list, a WEAK link that
        names the target without closing it

    Recording that work was taken on (adoption) or carried (deferral) must not
    close the item that verifies the work actually landed.

    Mutates the event in place. No-op when no suffix is present so callers can
    apply this unconditionally. Malformed tokens (not 12-hex) are silently
    dropped — typos shouldn't break adoption. A caller-supplied
    metadata.resolves is NEVER stripped or rewritten: routing decides only
    where the SUFFIX-derived ids land. Existing IDs in the target field are
    preserved; duplicates are de-duped.

    Callers must apply `metadata` to the event BEFORE calling this — the
    predicate reads the disposition off the event. Both entry points already
    do (`build_event`, `_common.make_event`).
    """
    content = event.get("content", "")
    match = _REFS_SUFFIX_RE.search(content)
    if not match:
        return
    cleaned = content[: match.start()].rstrip()
    tokens = _REFS_SPLIT_RE.split(match.group(1).strip())
    new_ids = [t for t in tokens if EVENT_ID_RE.match(t)]
    if not new_ids:
        event["content"] = cleaned
        return
    if is_closing(event):
        merge_resolves(event, new_ids)
    else:
        merge_references(event, new_ids)
    event["content"] = cleaned


def parse_json_arg(value: str, name: str) -> list | dict:
    """Parse a JSON string argument, exit on failure or oversized input."""
    if len(value) > MAX_JSON_ARG_SIZE:
        print(
            f"Error: --{name} value too large "
            f"({len(value)} > {MAX_JSON_ARG_SIZE} bytes)",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON for --{name}: {e}", file=sys.stderr)
        sys.exit(1)


def build_event(args: argparse.Namespace) -> dict:
    """Construct an event dict from parsed CLI arguments.

    Does not validate required fields — that's validate_event's job.
    """
    event: dict = {
        "id": generate_id(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": args.type,
        "agent_id": args.agent,
        "content": args.content,
        "schema_version": 1,
    }

    # Universal optional fields
    if args.references:
        event["references"] = parse_json_arg(args.references, "references")
    if args.metadata:
        event["metadata"] = parse_json_arg(args.metadata, "metadata")

    # Type-specific fields — just map args to event fields, no validation
    match args.type:
        case "debt":
            if args.files is not None:
                event["files"] = parse_json_arg(args.files, "files")

        case "customer_intent":
            if args.intent_status is not None:
                event["intent_status"] = args.intent_status

        case "status":
            if args.working_on is not None:
                event["working_on"] = parse_json_arg(args.working_on, "working-on")
            else:
                event["working_on"] = []

        case "decision" | "convention":
            if args.topic is not None:
                event["topic"] = args.topic

        case "concern":
            if args.severity:
                event["severity"] = args.severity
            if args.files is not None:
                event["files"] = parse_json_arg(args.files, "files")
            else:
                extracted = extract_files_from_content(args.content or "")
                if extracted:
                    event["files"] = extracted

        case "question":
            if args.priority is not None:
                event["priority"] = args.priority

        case "session_end":
            if args.duration_seconds is not None:
                event["duration_seconds"] = args.duration_seconds
            if args.event_count is not None:
                event["event_count"] = args.event_count
            if args.unresolved_items:
                event["unresolved_items"] = parse_json_arg(
                    args.unresolved_items, "unresolved-items"
                )
            if args.working_on:
                event["working_on"] = parse_json_arg(args.working_on, "working-on")
        case "retrospective":
            if args.keep:
                event["keep"] = parse_json_arg(args.keep, "keep")
            if args.fix:
                event["fix"] = parse_json_arg(args.fix, "fix")
            if args.try_items:
                event["try"] = parse_json_arg(args.try_items, "try-items")

    extract_refs_suffix(event)
    return event


def _format_budget_epilog() -> str:
    """Generate CLI help epilog with content budgets and usage examples."""
    entries = [
        f"{t}={b}" if b is not None else f"{t}=uncapped"
        for t, b in CONTENT_BUDGETS.items()
    ]
    lines = ["Content budgets (chars):"]
    for i in range(0, len(entries), 4):
        lines.append("  " + "  ".join(entries[i : i + 4]))
    lines.append("Over-budget events are rejected with an actionable error.")
    lines.append("")
    lines.append("Examples:")
    lines.append(
        "  append.sh --smm-dir DIR --type status --agent main"
        ' --content "Starting refactor" --working-on \'["src/auth.py"]\''
    )
    lines.append(
        "  append.sh --smm-dir DIR --type decision --agent main"
        ' --content "Use typed errors" --topic error-handling'
    )
    lines.append(
        "  append.sh --smm-dir DIR --type concern --agent main"
        ' --content "Missing validation" --severity medium'
    )
    lines.append(
        "  append.sh --smm-dir DIR --type debt --agent main"
        ' --content "Legacy code" --files \'["src/legacy.ts"]\''
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for append operations."""
    parser = argparse.ArgumentParser(
        description="Append an event to the SMM event log",
        epilog=_format_budget_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Optional SMM directory override (avoids data-root env var issues)
    parser.add_argument(
        "--smm-dir", type=Path, help="SMM directory (auto-resolved if omitted)"
    )

    # Universal required
    parser.add_argument("--type", required=True, choices=VALID_TYPES, help="Event type")
    parser.add_argument("--agent", required=True, help="Agent ID")
    parser.add_argument("--content", required=True, help="Event content")

    # Universal optional
    parser.add_argument("--references", help="JSON array of referenced event IDs")
    parser.add_argument("--metadata", help="JSON object of metadata")

    # Type-specific
    parser.add_argument(
        "--working-on",
        help="JSON array of file paths",
    )
    parser.add_argument("--topic", help="Topic string")
    parser.add_argument("--priority", help="Priority emoji")
    parser.add_argument(
        "--severity",
        choices=["high", "medium", "low"],
    )

    # debt/concern specific
    parser.add_argument("--files", help="JSON array of file paths (debt, concern)")

    # customer_intent specific
    parser.add_argument(
        "--intent-status",
        choices=["open", "delivered", "superseded"],
        help="Intent status (customer_intent)",
    )

    # session_end specific
    parser.add_argument(
        "--duration-seconds",
        type=float,
        help="Session duration",
    )
    parser.add_argument(
        "--event-count",
        type=int,
        help="Event count",
    )
    parser.add_argument(
        "--unresolved-items",
        help="JSON array of unresolved IDs",
    )
    # retrospective specific
    parser.add_argument("--keep", help="JSON array of keep items (retrospective)")
    parser.add_argument("--fix", help="JSON array of fix items (retrospective)")
    parser.add_argument("--try-items", help="JSON array of try items (retrospective)")

    return parser
