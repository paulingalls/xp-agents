#!/usr/bin/env python3
"""Sprint sizing metrics: commit-to-story attribution and aggregation.

Computes per-story and per-size metrics using metadata.story_id set
at commit time. Used by retrospective.py to enrich .retro-input.json
when a sprint has ended.
"""

from __future__ import annotations

from pathlib import Path

import sprint_store

_EM_DASH = "\u2014"


def extract_file_domain_paths(file_domain: list[str]) -> set[str]:
    """Extract file paths from file_domain entries.

    Entries are "path — description" or just "path".
    """
    paths: set[str] = set()
    for entry in file_domain:
        if _EM_DASH in entry:
            path = entry.split(_EM_DASH, 1)[0].strip()
        else:
            path = entry.strip()
        if path:
            paths.add(path)
    return paths


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


def _attribute_commits(
    commit_events: list[dict], stories: list[dict]
) -> dict[str, dict]:
    """Attribute commits to stories via metadata.story_id.

    Uses story_id set at commit time by _resolve_story_id().
    Commits without story_id are not attributed.
    Files are deduplicated per story using set union.
    """
    story_ids = {s["id"] for s in stories}
    story_domains = {
        s["id"]: extract_file_domain_paths(s.get("file_domain", [])) for s in stories
    }

    commit_counts: dict[str, int] = {sid: 0 for sid in story_ids}
    all_files: dict[str, set[str]] = {sid: set() for sid in story_ids}
    domain_files: dict[str, set[str]] = {sid: set() for sid in story_ids}

    for commit in commit_events:
        committed_files = set(commit.get("files", []))
        if not committed_files:
            continue

        story_id = (commit.get("metadata") or {}).get("story_id")
        if not story_id or story_id not in story_ids:
            continue

        commit_counts[story_id] += 1
        all_files[story_id] |= committed_files
        domain = story_domains[story_id]
        domain_files[story_id] |= {
            f for f in committed_files if file_matches_domain(f, domain)
        }

    metrics: dict[str, dict] = {}
    for s in stories:
        sid = s["id"]
        total = len(all_files[sid])
        in_d = len(domain_files[sid])
        metrics[sid] = {
            "commits": commit_counts[sid],
            "files_changed": total,
            "in_domain_files": in_d,
            "out_of_domain_files": total - in_d,
            "domain_accuracy": in_d / total if total > 0 else 0.0,
        }

    return metrics


def _per_size_aggregates(
    story_metrics: dict[str, dict], stories: list[dict]
) -> dict[str, dict]:
    """Aggregate metrics by story size (S/M/L)."""
    by_size: dict[str, list[dict]] = {}
    size_map = {s["id"]: s["size"] for s in stories}

    for sid, m in story_metrics.items():
        size = size_map.get(sid, "?")
        by_size.setdefault(size, []).append(m)

    result: dict[str, dict] = {}
    for size, items in sorted(by_size.items()):
        count = len(items)
        total_commits = sum(m["commits"] for m in items)
        total_files = sum(m["files_changed"] for m in items)
        result[size] = {
            "count": count,
            "avg_commits": total_commits / count,
            "avg_files": total_files / count,
        }

    return result


def compute_sizing_analysis(smm_dir: Path, events: list[dict]) -> dict | None:
    """Compute full sizing analysis for a completed sprint.

    Returns sizing_analysis dict or None if no sprint data.
    """
    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return None

    velocity = sprint_store.compute_velocity(sprint)
    started = sprint.get("started", "")

    commit_events = [
        e
        for e in events
        if e.get("type") == "commit" and e.get("ts", "")[:10] >= started
    ]

    story_metrics = _attribute_commits(commit_events, sprint["stories"])
    per_size = _per_size_aggregates(story_metrics, sprint["stories"])

    per_story = []
    for s in sprint["stories"]:
        m = story_metrics[s["id"]]
        # Flags mis-attribution or unclosed-done — surfaced in retro.
        per_story.append(
            {
                "id": s["id"],
                "title": s["title"],
                "status": s["status"],
                "size": s["size"],
                **m,
                "attribution_anomaly": s["status"] == "deferred" and m["commits"] > 0,
            }
        )

    return {
        "sprint_id": sprint["sprint_id"],
        "goal": sprint["goal"],
        "started": started,
        "velocity": velocity,
        "per_story": per_story,
        "per_size": per_size,
    }
