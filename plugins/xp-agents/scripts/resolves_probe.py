#!/usr/bin/env python3
"""Resolves-trailer probe: find open concerns a commit should auto-link.

Pure module called by two paths:
- bash_post_tool._handle_commit (post-commit nudge + status event)
- xp-quality-review/scripts/probe_candidates.py (pre-commit probe)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
from event_schema import (
    METADATA_KEY_COMMIT_HASH,
    METADATA_KEY_PROBE_CANDIDATES,
    STATUS_CONTENT_RESOLVES_PROBE,
)

PROBE_CANDIDATE_LIMIT = 5


def find_probe_candidates(
    smm_dir: Path,
    commit_files: list[str],
    resolves: list[str],
    cwd: str,
) -> list[dict]:
    """Open concerns whose files intersect commit, minus already-resolved, capped."""
    open_matches = commits.open_concerns_matching_commit(smm_dir, commit_files, cwd)
    return [c for c in open_matches if c["id"] not in resolves][:PROBE_CANDIDATE_LIMIT]


def build_nudge_lines(candidates: list[dict]) -> list[str]:
    """Format auto-link nudge text for each candidate."""
    return [
        f"Auto-link nudge: concern {c['id']} — {(c.get('content') or '')[:80]}. "
        f"If correct, re-commit with:\n"
        f'  git commit --amend --trailer "Resolves-Event: {c["id"]}"'
        for c in candidates
    ]


def build_probe_status_event(
    candidates: list[dict], commit_hash: str | None, agent_id: str
) -> dict | None:
    """Probe status event dict (None when no candidates)."""
    if not candidates:
        return None
    return _common.make_event(
        _common.STATUS,
        agent_id,
        f"{STATUS_CONTENT_RESOLVES_PROBE}: {len(candidates)} candidates",
        working_on=[],
        metadata={
            METADATA_KEY_PROBE_CANDIDATES: [c["id"] for c in candidates],
            METADATA_KEY_COMMIT_HASH: commit_hash,
        },
    )
