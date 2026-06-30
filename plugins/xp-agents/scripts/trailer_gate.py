#!/usr/bin/env python3
"""Pre-merge Resolves-Event trailer advisory.

The `Resolves-Event:` trailer convention is advisory-only — nothing checks it
at the moment it matters. The retrospective computes a resolves_link_rate, but
only AFTER the session. This module surfaces that same rate as a pre-merge
advisory at close-merge time, naming the un-trailered eligible commits so the
user can act while the commits are still in reach.

It is a THIN REUSE LAYER over retro_metrics' canonical eligibility
(`eligible_trailer_commits` + `has_resolves_trailer`), NOT a reimplementation:
a divergent candidate-gate denominator silently mis-scores (retro_metrics'
own comments warn it floors the rate ~1/3, making 0.80 unachievable).

Advisory only — `advisory()` returns a string for the caller to print; it
never changes a merge's exit code. Stdlib-only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import retro_metrics
import sprint_store
from event_schema import METADATA_KEY_COMMIT_HASH

# At least this fraction of eligible commits must carry trailers, or the
# advisory fires. Single source of truth lives with the metric it gates —
# retro_metrics.RESOLVES_LINK_RATE_TARGET — so the pre-merge advisory and the
# retro's Fix threshold can never drift.
THRESHOLD = retro_metrics.RESOLVES_LINK_RATE_TARGET

# Sentinel for the optional ``sprint`` pre-read: ``None`` is a VALID passed
# value (absent/corrupt sprint → None, fail open), so it can't double as "not
# provided". ``events`` needs no sentinel — a real pre-read is always a list.
_UNSET = object()


def _started_from(smm_dir: Path, sprint: object) -> str | None:
    """The sprint's start date, or None (fail open → no window filter).

    ``sprint is _UNSET`` → load own; else use the passed value (which may be a
    dict or None). None when the sprint is absent OR corrupt/unreadable: the
    advisory must never crash a close merge over a SMM-state problem, so it
    degrades to the unwindowed denominator (same fail-open posture as
    close_common's merge helpers).
    """
    if sprint is _UNSET:
        try:
            sprint = sprint_store.load_sprint(smm_dir)
        except (sprint_store.SprintCorruptError, OSError):
            return None
    return sprint.get("started") if isinstance(sprint, dict) else None


def advisory(
    smm_dir: Path,
    *,
    events: list[dict] | None = None,
    sprint: object = _UNSET,
) -> str | None:
    """Return a pre-merge trailer advisory, or None when none is warranted.

    None when there are no eligible commits (nothing to nudge) or when the
    trailer ratio already meets THRESHOLD. Otherwise a multi-line string
    naming the ratio, the threshold, and each un-trailered eligible commit
    (short hash + subject). The caller prints it — this never blocks.

    Optional ``events``/``sprint`` pre-reads let ``cmd_merge`` share ONE locked
    events read + ONE sprint load with the merge-event append (closes the
    recorded double-read debt). ``events is None`` → read own under flock;
    ``sprint is _UNSET`` → load own. Standalone ``advisory(smm_dir)`` reads its
    own — the independence guarantee; a passed snapshot only ever skips the
    re-read, never changes the output.
    """
    if events is None:
        events = _common.read_events_locked(smm_dir, "trailer-gate")
    eligible = retro_metrics.eligible_trailer_commits(
        events, _started_from(smm_dir, sprint)
    )
    if not eligible:
        return None

    untrailered = [
        e
        for e in eligible
        if not retro_metrics.has_resolves_trailer(e.get("metadata") or {})
    ]
    total = len(eligible)
    hits = total - len(untrailered)
    if hits / total >= THRESHOLD:
        return None

    pct = round(hits / total * 100)
    threshold_pct = round(THRESHOLD * 100)
    lines = [
        f"Resolves-Event trailer advisory: {hits}/{total} ({pct}%) of eligible "
        f"commits carry trailers, below the {threshold_pct}% target.",
        "Un-trailered eligible commits (touched a tracked concern/debt/question):",
    ]
    for e in untrailered:
        commit_hash = (e.get("metadata") or {}).get(METADATA_KEY_COMMIT_HASH) or ""
        short = commit_hash[:7] if commit_hash else "???????"
        subject = (e.get("content") or "").splitlines()[0] if e.get("content") else ""
        lines.append(f"  - {short} {subject}".rstrip())
    lines.append(
        "Add Resolves-Event: <id> trailers while these commits are in reach "
        "(advisory only; the merge proceeded)."
    )
    return "\n".join(lines)
