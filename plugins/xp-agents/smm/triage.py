#!/usr/bin/env python3
"""Shared triage helpers for concern/debt/question resolution.

Used by xp-work-selection and xp-accept preloads to find unresolved
events and detect file overlap with commits.
"""

import event_schema

_EM_DASH = "—"


def find_unresolved(
    events: list[dict],
    event_type: str,
    resolved_ids: set[str],
) -> list[dict]:
    """Return unresolved events of a given type, newest first."""
    unresolved = [
        e
        for e in events
        if e.get("type") == event_type and e.get("id") not in resolved_ids
    ]
    return sorted(unresolved, key=lambda e: e.get("ts", ""), reverse=True)


def find_overlapping_commits(
    concern: dict,
    events: list[dict],
) -> list[dict]:
    """Find commit events whose files overlap the concern's files.

    Only considers commits after the concern's timestamp.
    """
    concern_files = set(concern.get("files") or [])
    if not concern_files:
        return []
    concern_ts = concern.get("ts", "")

    overlapping = []
    for e in events:
        if e.get("type") != event_schema.EVENT_TYPE_COMMIT:
            continue
        if e.get("ts", "") <= concern_ts:
            continue
        commit_files = set(e.get("files") or [])
        if concern_files & commit_files:
            overlapping.append(e)
    return overlapping


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
