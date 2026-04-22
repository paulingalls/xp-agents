#!/usr/bin/env python3
"""Resolves-trailer probe: find open concerns/debts a commit should auto-link.

Pure module called by two paths:
- bash_post_tool._handle_commit (post-commit nudge + status event)
- xp-quality-review/scripts/probe_candidates.py (pre-commit probe)
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import commits
import worktree
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
    events: list[dict] | None = None,
    resolutions: dict | None = None,
) -> list[dict]:
    """Open concerns/debts with file overlap, minus resolved, capped."""
    open_matches = commits.open_issues_matching_commit(
        smm_dir, commit_files, cwd, events=events, resolutions=resolutions
    )
    return [c for c in open_matches if c["id"] not in resolves][:PROBE_CANDIDATE_LIMIT]


def build_nudge_lines(candidates: list[dict]) -> list[str]:
    """Format auto-link nudge text for each candidate."""
    return [
        f"Auto-link nudge: {c.get('type', 'concern')} {c['id']}"
        f" — {(c.get('content') or '')[:80]}. "
        f"If correct, re-commit with:\n"
        f'  git commit --amend --trailer "Resolves-Event: {c["id"]}"'
        for c in candidates
    ]


def compute_fingerprint(files: list[str], concern_ids: list[str], cwd: str) -> str:
    """sha256 over sorted normalized files + sorted issue ids. Order-invariant.

    Used by /xp-quality-review pre-commit and bash_post_tool._handle_commit to
    detect when the pre-commit probe and the post-commit commit are covering
    the same set of (staged files, open concerns/debts) — fingerprint match
    means the post-commit nudge is redundant. Files that fail to normalize are
    silently skipped, mirroring commits.open_issues_matching_commit so both
    sides of the pre/post comparison agree on which files are fingerprinted.
    """
    norm_files: set[str] = set()
    for f in files:
        try:
            norm_files.add(worktree.normalize_path(f, cwd))
        except (ValueError, OSError):
            continue
    payload = json.dumps(
        {"files": sorted(norm_files), "ids": sorted(concern_ids)}, sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


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
