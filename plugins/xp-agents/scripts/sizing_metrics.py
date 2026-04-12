#!/usr/bin/env python3
"""Sprint sizing metrics: commit-to-story attribution and aggregation.

Computes per-story and per-size metrics by matching commit events
against story file_domain entries. Used by retrospective.py to enrich
.retro-input.json when a sprint has ended.
"""

from __future__ import annotations

from pathlib import Path

import sprint_store

_EM_DASH = "\u2014"


def _extract_file_domain_paths(file_domain: list[str]) -> set[str]:
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


def _attribute_commits(
    commit_events: list[dict], stories: list[dict]
) -> dict[str, dict]:
    """Attribute commits to stories via file_domain overlap.

    Returns per-story metrics keyed by story id.
    """
    story_domains = {
        s["id"]: _extract_file_domain_paths(s.get("file_domain", [])) for s in stories
    }

    metrics: dict[str, dict] = {}
    for s in stories:
        metrics[s["id"]] = {
            "commits": 0,
            "files_changed": 0,
            "in_domain_files": 0,
            "out_of_domain_files": 0,
            "domain_accuracy": 0.0,
        }

    for commit in commit_events:
        committed_files = set(commit.get("files", []))
        if not committed_files:
            continue

        for story in stories:
            sid = story["id"]
            domain = story_domains[sid]
            if not domain:
                continue

            overlap = committed_files & domain
            if not overlap:
                continue

            m = metrics[sid]
            m["commits"] += 1
            m["files_changed"] += len(committed_files)
            m["in_domain_files"] += len(overlap)
            m["out_of_domain_files"] += len(committed_files) - len(overlap)

    for _sid, m in metrics.items():
        if m["files_changed"] > 0:
            m["domain_accuracy"] = m["in_domain_files"] / m["files_changed"]

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
        per_story.append(
            {
                "id": s["id"],
                "title": s["title"],
                "status": s["status"],
                "size": s["size"],
                **m,
            }
        )

    return {
        "sprint_id": sprint["sprint_id"],
        "goal": sprint["goal"],
        "velocity": velocity,
        "per_story": per_story,
        "per_size": per_size,
    }
