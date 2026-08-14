#!/usr/bin/env python3
"""Reading a commit MESSAGE — text in, text out, and never a subprocess.

Split from `commits.py`, which had grown two jobs: this half parses strings the
caller already has, while everything left there ASKS GIT (`_run_git` and down).
The seam is observable, not stylistic — nothing here opens a repo, so these
functions are testable on a literal and run identically with no git on PATH.

Re-exported by identity from `commits.py`, the pattern `smm/_events_replace.py`
and `smm/_append_lock.py` already establish: every caller reaches these as
`commits.<name>`, so the extraction moves code without moving any call site.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from smm_schema import EVENT_ID_RE

_RESOLVES_TRAILER_RE = re.compile(r"(?im)^resolves-event:[ \t]*(.*)\n?")
# Boundary-anchored twin of smm_schema.EVENT_ID_RE — keep in sync if the
# canonical event-ID format changes.
_BARE_EVENT_ID_RE = re.compile(r"\b[0-9a-f]{12}\b")


def parse_commit_message(tool_response: str) -> str | None:
    """Extract first line of commit message from git output."""
    match = re.search(r"\[[\w/.-]+\s+\w+\]\s+(.+)", tool_response)
    if match:
        return match.group(1).strip()
    return None


def extract_implicit_event_ids(body: str | None, known_ids: set[str]) -> list[str]:
    """Scan commit body for bare 12-hex event IDs matching open events.

    Agents sometimes reference an event ID in prose (e.g., "closes concern
    <12-hex-id>") without the formal `Resolves-Event:` trailer. This helper
    surfaces those bare IDs so callers can accept the link and optionally
    nudge for the formal trailer.

    Only returns IDs that appear in `known_ids` — the caller supplies the
    set of open concern/question/debt event IDs. Dedups in first-seen order.
    """
    if not body or not known_ids:
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for match in _BARE_EVENT_ID_RE.finditer(body):
        event_id = match.group(0)
        if event_id in known_ids and event_id not in seen:
            ids.append(event_id)
            seen.add(event_id)
    return ids


def extract_resolves_trailer(body: str | None) -> tuple[list[str], str, bool]:
    """Parse Resolves-Event: trailers from a commit body.

    Trailer format (case-insensitive key, line-anchored):
        Resolves-Event: <12-hex-id>[, <id>...]

    Multiple trailer lines are supported; IDs are deduplicated in first-seen
    order. IDs that aren't exactly 12 lowercase-hex chars are rejected. The
    returned body has all matched trailer lines removed (including the newline)
    so callers can use it directly as the stored commit event content.

    has_trailer is True when any Resolves-Event: line was found, even if
    the value was "none" or otherwise not a valid hex ID. This distinguishes
    "developer followed the discipline but nothing to resolve" from
    "developer forgot the trailer entirely".
    """
    if not body:
        return [], body or "", False
    ids: list[str] = []
    seen: set[str] = set()
    has_trailer = False
    for match in _RESOLVES_TRAILER_RE.finditer(body):
        has_trailer = True
        for raw in match.group(1).split(","):
            event_id = raw.strip().lower()
            if EVENT_ID_RE.match(event_id) and event_id not in seen:
                ids.append(event_id)
                seen.add(event_id)
    cleaned = _RESOLVES_TRAILER_RE.sub("", body)
    return ids, cleaned, has_trailer
