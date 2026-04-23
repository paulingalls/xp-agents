#!/usr/bin/env python3
"""Resolves-trailer probe: find open concerns/debts a commit should auto-link.

Called by two paths:
- pre_tool_bash.run (pre-commit nudge + status event)
- xp-quality-review/scripts/probe_candidates.py (quality-review pre-commit probe)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
from event_schema import (
    METADATA_KEY_PROBE_CANDIDATES,
    STATUS_CONTENT_RESOLVES_PROBE,
)

PROBE_CANDIDATE_LIMIT = 5


def find_probe_candidates(
    smm_dir: Path,
    commit_files: list[str],
    resolves: list[str],
    cwd: str,
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> list[dict]:
    """Open concerns/debts with file overlap, minus resolved, capped."""
    open_matches = commits.open_issues_matching_commit(
        smm_dir, commit_files, cwd, events=events, resolutions=resolutions
    )
    return [c for c in open_matches if c["id"] not in resolves][:PROBE_CANDIDATE_LIMIT]


def build_nudge_lines(candidates: list[dict]) -> list[str]:
    """Format grouped nudge block with header, items, and ready-to-copy trailer."""
    if not candidates:
        return []
    items = []
    for c in candidates:
        raw = c.get("content") or ""
        content = raw[:80] + ("..." if len(raw) > 80 else "")
        items.append(f"- [{c.get('type', 'concern')}] {c['id']}: {content}")
    ids = ", ".join(c["id"] for c in candidates)
    block = (
        "Overlapping open events — add Resolves-Event trailer "
        "if this commit addresses them:\n"
        + "\n".join(items)
        + f"\nReady-to-use trailer: Resolves-Event: {ids}"
    )
    return [block]


def emit_probe_status(smm_dir: "Path", candidates: list[dict], agent_id: str) -> None:
    """Write a probe status event to events.jsonl."""
    if not candidates:
        return
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        f"{STATUS_CONTENT_RESOLVES_PROBE}: {len(candidates)} candidates",
        working_on=[],
        metadata={
            METADATA_KEY_PROBE_CANDIDATES: [c["id"] for c in candidates],
        },
    )
    _common.append_safe(smm_dir, event)
