#!/usr/bin/env python3
"""Sprint story metrics: commit-to-story attribution and aggregation.

Computes per-story metrics using metadata.story_id set at commit time.
Used by retrospective.py to enrich .retro-input.json when a sprint
has ended.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import _common
import sprint_store
import triage

# Re-export for backward compat — canonical impl lives in smm/triage.py
extract_file_domain_paths = triage.extract_file_domain_paths

# Canonical regexes for story-prefix detection. Imported by the
# post-commit attributor (bash_post_tool._resolve_story_id).
STORY_PREFIX_RE = re.compile(r"^\s*\[(story-\d+)\]")
BRACKET_PREFIX_RE = re.compile(r"^\s*\[")


def file_matches_domain(file_path: str, domain: set[str]) -> bool:
    """Check if a file matches the domain.

    Handles path prefixes (a/b/scripts/foo.py matches scripts/foo.py)
    and test-to-source mapping (test_foo.py matches foo.py).
    """
    for d in domain:
        if file_path == d or file_path.endswith("/" + d):
            return True
    name = Path(file_path).name
    if name.startswith("test_"):
        source_name = name[5:]
        for d in domain:
            if Path(d).name == source_name:
                return True
    return False


def resolve_dominant_story(
    in_progress: list[dict], files: list[str]
) -> tuple[str | None, int]:
    """Find the in-progress story with highest file-domain overlap.

    Returns (story_id, overlap_count):
      - story_id: id of the highest-overlap story; None when no story matches
                  or 2+ stories share the highest non-zero overlap (tied)
      - overlap_count: count of files matching the winning story's domain
                       (0 when story_id is None)

    Used by post-commit attribution (`_resolve_story_id` Tier 2b).
    """
    best_id: str | None = None
    best_overlap = 0
    tied = False
    for story in in_progress:
        domain = extract_file_domain_paths(
            story.get("file_domain", []), candidate_files=files
        )
        if not domain:
            continue
        overlap = sum(1 for f in files if file_matches_domain(f, domain))
        if overlap > best_overlap:
            best_overlap = overlap
            best_id = story["id"]
            tied = False
        elif overlap == best_overlap and best_overlap > 0:
            tied = True
    if tied:
        return (None, 0)
    return (best_id, best_overlap)


def _attribute_commits(
    commit_events: list[dict], stories: list[dict]
) -> dict[str, dict]:
    """Attribute commits to stories via metadata.story_id.

    Uses story_id set at commit time by _resolve_story_id().
    Commits without story_id are not attributed.
    Files are deduplicated per story using set union.
    """
    story_ids = {s["id"] for s in stories}
    # Union all committed files once so glob entries in file_domain expand
    # against the historical commit set (files may no longer exist on disk).
    all_committed: set[str] = set()
    for commit in commit_events:
        all_committed |= set(commit.get("files", []))
    story_domains = {
        s["id"]: extract_file_domain_paths(
            s.get("file_domain", []), candidate_files=all_committed
        )
        for s in stories
    }

    commit_counts: dict[str, int] = {sid: 0 for sid in story_ids}
    all_files: dict[str, set[str]] = {sid: set() for sid in story_ids}

    for commit in commit_events:
        committed_files = set(commit.get("files", []))
        if not committed_files:
            continue

        story_id = (commit.get("metadata") or {}).get("story_id")
        if not story_id or story_id not in story_ids:
            continue

        commit_counts[story_id] += 1
        all_files[story_id] |= committed_files

    metrics: dict[str, dict] = {}
    for s in stories:
        sid = s["id"]
        files = all_files[sid]
        domain = story_domains[sid]
        cascade = sum(1 for f in files if not file_matches_domain(f, domain))
        metrics[sid] = {
            "commits": commit_counts[sid],
            "files_changed": len(files),
            "cascade_size": cascade,
        }

    return metrics


def _per_agent_event_counts(events: list[dict], started: str) -> dict:
    """Count max events-to-commit per agent within the sprint window."""
    counters: dict[str, int] = {}
    maxima: dict[str, int] = {}

    for e in events:
        if e.get("ts", "")[:10] < started:
            continue
        agent_id = e.get("agent_id", "main")
        if e.get("type") == _common.COMMIT:
            cur = counters.get(agent_id, 0)
            maxima[agent_id] = max(maxima.get(agent_id, 0), cur)
            counters[agent_id] = 0
        else:
            counters[agent_id] = counters.get(agent_id, 0) + 1

    for agent_id, cur in counters.items():
        maxima[agent_id] = max(maxima.get(agent_id, 0), cur)

    return {
        agent_id: {"max_events_to_commit": count} for agent_id, count in maxima.items()
    }


def compute_story_analysis(smm_dir: Path, events: list[dict]) -> dict | None:
    """Compute per-story metrics for a completed sprint.

    Returns story analysis dict or None if no sprint data.
    """
    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return None

    velocity = sprint_store.compute_velocity(sprint)
    started = sprint.get("started", "")

    target_sprint_id = sprint["sprint_id"]
    commit_events = [
        e
        for e in events
        if e.get("type") == _common.COMMIT
        and e.get("ts", "")[:10] >= started
        and (e.get("metadata") or {}).get("sprint_id", target_sprint_id)
        == target_sprint_id
    ]

    attribution = _attribute_commits(commit_events, sprint["stories"])

    per_story = []
    for s in sprint["stories"]:
        m = attribution[s["id"]]
        per_story.append(
            {
                "id": s["id"],
                "title": s["title"],
                "status": s["status"],
                **m,
                "code_free": not bool(s.get("file_domain")),
                "attribution_anomaly": (s["status"] == "deferred" and m["commits"] > 0),
            }
        )

    return {
        "sprint_id": sprint["sprint_id"],
        "goal": sprint["goal"],
        "started": started,
        "velocity": velocity,
        "per_story": per_story,
        "per_agent": _per_agent_event_counts(events, started),
    }
