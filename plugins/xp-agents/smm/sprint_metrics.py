#!/usr/bin/env python3
"""Computed-field helpers for sprint.json (pure functions on sprint dict).

Extracted from sprint_store.py once that module crossed 500 lines.
sprint_store re-exports every name defined here so existing call sites
(`from sprint_store import compute_velocity`) keep working.

`load_sprint` is imported lazily inside `next_sprint_id` so this module can
import cleanly without a cycle when sprint_store re-exports back.
"""

import json
from pathlib import Path

from sprint_schema import VALID_STORY_STATUSES


def count_by_status(sprint: dict) -> dict[str, int]:
    """Count stories by status.

    Keys derived from VALID_STORY_STATUSES so adding a new status value to
    the schema automatically extends this dict — no separate edit needed.
    """
    counts = {s: 0 for s in VALID_STORY_STATUSES}
    for s in sprint["stories"]:
        status = s["status"]
        if status in counts:
            counts[status] += 1
    return counts


def compute_velocity(sprint: dict) -> dict[str, int]:
    """Compute velocity metrics from sprint data."""
    counts = count_by_status(sprint)
    total = sum(counts.values())
    return {
        "stories_planned": total,
        "stories_delivered": counts["done"],
        "stories_carried": counts["deferred"],
    }


def compute_blockers(sprint: dict) -> list[str]:
    """Compute blockers from dependencies + statuses."""
    statuses = {s["id"]: s["status"] for s in sprint["stories"]}
    blockers: list[str] = []
    for s in sprint["stories"]:
        for dep_id in s.get("dependencies", []):
            dep_status = statuses.get(dep_id, "")
            if dep_status and dep_status != "done":
                blockers.append(f"{s['id']} blocked by {dep_id} ({dep_status})")
    return blockers


def list_stories(sprint: dict, *, status: str | None = None) -> list[dict]:
    """Return stories, optionally filtered by status."""
    stories = sprint["stories"]
    if status is not None:
        stories = [s for s in stories if s["status"] == status]
    return stories


def next_sprint_id(smm_dir: Path) -> str:
    """Determine the next sprint ID: MAX EXISTING id + 1 across every
    surviving source (live sprint, archived sprints/*.json, sprint-start
    events), so archiving sprint.json can never regress the counter.

    Default: 'sprint-001' if no history exists anywhere.
    """
    from sprint_store import load_sprint

    ids: set[str] = set()

    sprint = load_sprint(smm_dir)
    if sprint is not None and sprint["sprint_id"]:
        ids.add(sprint["sprint_id"])
    ids.update(_archived_sprint_ids(smm_dir))
    ids.update(_sprint_start_ids(smm_dir))

    nums = []
    for sid in ids:
        parts = sid.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            nums.append(int(parts[1]))

    if not nums:
        return "sprint-001"
    return f"sprint-{max(nums) + 1:03d}"


def _archived_sprint_ids(smm_dir: Path) -> set[str]:
    """Read sprint_id from every archived sprints/*.json.

    A missing/corrupt/unparseable archive file is skipped, not fatal.
    """
    ids: set[str] = set()
    sprints_dir = smm_dir / "sprints"
    if not sprints_dir.is_dir():
        return ids
    for path in sprints_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sid = data.get("sprint_id")
        if sid:
            ids.add(sid)
    return ids


def _sprint_start_ids(smm_dir: Path) -> set[str]:
    """Read sprint_id from every sprint-start event in events.jsonl."""
    from append_validation import parse_jsonl

    path = smm_dir / "events.jsonl"
    if path.is_symlink():
        return set()
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return set()
    events, _ = parse_jsonl(raw)
    ids: set[str] = set()
    for e in events:
        if (
            e.get("type") == "sprint"
            and (e.get("metadata") or {}).get("action") == "start"
        ):
            sid = (e.get("metadata") or {}).get("sprint_id")
            if sid:
                ids.add(sid)
    return ids
