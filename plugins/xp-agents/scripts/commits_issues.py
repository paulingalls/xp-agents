#!/usr/bin/env python3
"""Matching open concerns/debts against commits.

Extracted from commits.py to stay under the 500-line cap. Re-exported from
`commits` (`from commits_issues import ...`) so `commits.open_issues_matching_commit`
and `commits.find_addressing_commits` keep working for existing callers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import resolution
import triage
import worktree


def open_issues_matching_commit(
    smm_dir: Path,
    commit_files: list[str],
    cwd: str,
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> list[dict]:
    """Return open concerns and debts whose files intersect commit_files.

    Used by bash_post_tool to nudge agents to add `Resolves-Event:`
    trailers on commits that touch files listed in an unresolved
    concern or debt. Paths are normalized on both sides so
    `./scripts/foo.py`, `scripts/foo.py`, and an absolute path all match.

    When ``events`` is provided, filters from the given list without reading
    disk — used by callers that already loaded events.
    When both ``events`` and ``resolutions`` are provided, skips computing
    resolutions entirely — avoids redundant work when the caller already has
    the resolution map (e.g. from ``load_events_with_resolutions``).
    """
    if not commit_files:
        return []
    if events is None:
        events, resolutions = _common.load_events_with_resolutions(smm_dir)
    elif resolutions is None:
        resolutions = resolution.compute_resolutions(events)
    resolved = resolutions["resolved_concern_ids"] | resolutions["resolved_debt_ids"]

    commit_set: set[str] = set()
    for f in commit_files:
        try:
            commit_set.add(worktree.normalize_path(f, cwd))
        except (ValueError, OSError):
            continue

    def _intersects(event_files: list) -> bool:
        if not isinstance(event_files, list):
            return False
        for f in event_files:
            if not isinstance(f, str):
                continue
            try:
                if worktree.normalize_path(f, cwd) in commit_set:
                    return True
            except (ValueError, OSError):
                continue
        return False

    return [
        e
        for e in events
        if e.get("type") in (_common.CONCERN, _common.DEBT)
        and e.get("id") not in resolved
        and _intersects(e.get("files") or [])
    ]


def find_addressing_commits(concern: dict, events: list[dict]) -> list[dict]:
    """Commits that may have addressed ``concern`` — the soft 'MAYBE
    ADDRESSED' nudge superset. UNION of two signals over commits dated
    after the concern:

    - file overlap (``triage.find_overlapping_commits``), and
    - the commit body citing the concern's id without a formal
      ``Resolves-Event:`` trailer (``commits.extract_implicit_event_ids``).

    File-overlap hits come first (stable with prior behavior); id-citing
    hits not already present are appended. Neither signal is
    authoritative — a formal trailer already resolves the concern, so a
    resolved concern never reaches this nudge; only prose citations on
    still-open concerns surface here. The id signal also catches commits
    that fixed the concern in a *different* file than it lists (including
    fileless concerns, invisible to file overlap).
    """
    import commits

    hits = list(triage.find_overlapping_commits(concern, events))
    cid = concern.get("id", "")
    if not cid:
        return hits
    seen = {h.get("id") for h in hits}
    concern_ts = concern.get("ts", "")
    for e in events:
        if e.get("type") != _common.COMMIT:
            continue
        if e.get("ts", "") <= concern_ts:
            continue
        if e.get("id") in seen:
            continue
        if commits.extract_implicit_event_ids(e.get("content") or "", {cid}):
            hits.append(e)
            seen.add(e.get("id"))
    return hits


__all__ = [
    "find_addressing_commits",
    "open_issues_matching_commit",
]
