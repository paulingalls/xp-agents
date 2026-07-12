#!/usr/bin/env python3
"""Pure filters over an event list for the adopt/defer/drop decision path.

No I/O, no flock — the caller does one locked read and feeds the list in, so
each filter is unit-testable without touching disk. Extracted from
work_selection_decide.py when it crossed the 500-line cap; the orchestration
(argparse, event construction, append) stays there and re-exports these names,
so callers and tests are unaffected by the move.

Names keep their leading underscore: they are internal to the work-selection
scripts, not a public surface — the trio of modules is one unit.
"""

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
from event_builder import REFERENCES_KEY  # noqa: E402
from event_schema import (  # noqa: E402
    DISPOSITION_DEFERRED,
    METADATA_KEY_DISPOSITION,
    METADATA_KEY_RESOLVES,
)

# 3 prior deferrals = next plain defer is refused.
_FORCE_CLOSE_THRESHOLD = 3


def _count_prior_defers_filter(events: list[dict], ref_ids: list[str]) -> int:
    """Pure filter: count status events with disposition=deferred that name any
    id in ref_ids. Each event contributes at most once.

    BOTH link fields count. A deferral records intent, so it now names its Try
    in the top-level `references` field — but every deferral written before
    that routing existed names it in metadata.resolves. Reading only the
    current field would reset every Try's deferral count to zero and silently
    disarm the FORCE-CLOSE gate on exactly the Tries it exists to catch.
    """
    if not ref_ids:
        return 0
    targets = set(ref_ids)
    count = 0
    for e in events:
        if e.get("type") != "status":
            continue
        meta = e.get("metadata") or {}
        if meta.get(METADATA_KEY_DISPOSITION) != DISPOSITION_DEFERRED:
            continue
        links = set(meta.get(METADATA_KEY_RESOLVES) or []) | set(
            e.get(REFERENCES_KEY) or []
        )
        if targets.intersection(links):
            count += 1
    return count


def _convention_topic_exists_filter(events: list[dict], topic: str) -> bool:
    """Pure filter: True if `events` contains a convention event with `topic`.
    Used to make force-drop convention emission idempotent — re-drops of
    the same Try MUST NOT append a duplicate convention.
    """
    for e in events:
        if e.get("type") == _common.CONVENTION and e.get("topic") == topic:
            return True
    return False


def _cascade_ids_filter(events: list[dict], tokens: set[str]) -> set[str]:
    """Pure filter: ids of resolvable events (debt/concern/discovery) whose
    id appears in tokens. Caller unions this into metadata.resolves so a
    drop also closes the underlying signal.
    """
    return {
        e.get("id", "")
        for e in events
        if e.get("type") in _common.PROBE_RESOLVABLE_TYPES and e.get("id", "") in tokens
    }


def _force_close_message(ref_ids: list[str], prior: int) -> str:
    refs = ", ".join(r[:8] for r in ref_ids)
    return (
        f"FORCE-CLOSE: Try refs [{refs}] have {prior} prior deferrals "
        f"(threshold {_FORCE_CLOSE_THRESHOLD}). Plain defer refused. "
        "Re-run with --force-adopt <topic>, --force-drop, "
        "or --force-defer-with-date <YYYY-MM-DD>."
    )
