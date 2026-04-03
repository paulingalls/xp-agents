#!/usr/bin/env python3
"""Sprint markdown parser for curation data.

Parses sprint.md into structured data: sprint header fields,
story counts by status, and blocker detection. Used by
materialize.prepare_curation_data() to populate the sprint key.
"""

import re
from typing import Any

_GOAL_RE = re.compile(r"^# Sprint:\s*(.+)$", re.MULTILINE)
_SPRINT_ID_RE = re.compile(r"\*\*Sprint ID:\*\*\s*(\S+)")
_STARTED_RE = re.compile(r"\*\*Started:\*\*\s*(\S+)")
_STORY_HEADER_RE = re.compile(r"^### (story-\d+):", re.MULTILINE)
_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(ready|in-progress|done|deferred)")
_DEPS_RE = re.compile(r"\*\*Dependencies:\*\*\s*(.+)")
_SIZE_RE = re.compile(r"\*\*Size:\*\*\s*(S|M|L)")
_TITLE_RE = re.compile(r"^### story-\d+:\s*(.+)$", re.MULTILINE)

_STATUS_KEY_MAP = {
    "ready": "ready",
    "in-progress": "in_progress",
    "done": "done",
    "deferred": "deferred",
}


def _empty_sprint() -> dict[str, Any]:
    """Return the empty sprint structure."""
    return {
        "sprint_id": "",
        "goal": "",
        "started": "",
        "stories_by_status": {
            "ready": 0,
            "in_progress": 0,
            "done": 0,
            "deferred": 0,
        },
        "blockers": [],
        "stories": [],
    }


def parse_sprint_data(content: str | None) -> dict[str, Any]:
    """Parse sprint.md content into structured sprint data.

    Returns a dict with sprint_id, goal, started, stories_by_status,
    and blockers. Returns empty structure for None, empty, or
    malformed content.
    """
    if not content:
        return _empty_sprint()

    result = _empty_sprint()

    # Parse header fields
    goal_m = _GOAL_RE.search(content)
    if goal_m:
        result["goal"] = goal_m.group(1).strip()

    id_m = _SPRINT_ID_RE.search(content)
    if id_m:
        result["sprint_id"] = id_m.group(1)

    started_m = _STARTED_RE.search(content)
    if started_m:
        result["started"] = started_m.group(1)

    # Split into story sections
    story_starts = list(_STORY_HEADER_RE.finditer(content))
    if not story_starts:
        return result

    # Collect all statuses first so blocker detection can cross-reference
    story_statuses: dict[str, str] = {}
    story_deps: dict[str, list[str]] = {}

    for i, match in enumerate(story_starts):
        story_id = match.group(1)
        start = match.start()
        end = story_starts[i + 1].start() if i + 1 < len(story_starts) else len(content)
        section = content[start:end]

        raw_status = ""
        status_m = _STATUS_RE.search(section)
        if status_m:
            raw_status = status_m.group(1)
            story_statuses[story_id] = raw_status
            key = _STATUS_KEY_MAP.get(raw_status)
            if key:
                result["stories_by_status"][key] += 1

        deps_m = _DEPS_RE.search(section)
        if deps_m:
            deps_text = deps_m.group(1).strip()
            if deps_text and deps_text.lower() != "none":
                dep_ids = [d.strip() for d in deps_text.split(",")]
                story_deps[story_id] = dep_ids

        # Per-story data with size and title
        size_m = _SIZE_RE.search(section)
        title_m = _TITLE_RE.search(section)
        result["stories"].append(
            {
                "id": story_id,
                "title": title_m.group(1).strip() if title_m else "",
                "status": raw_status,
                "size": size_m.group(1) if size_m else "",
            }
        )

    for story_id, deps in story_deps.items():
        for dep_id in deps:
            dep_status = story_statuses.get(dep_id, "")
            if dep_status and dep_status != "done":
                result["blockers"].append(
                    f"{story_id} blocked by {dep_id} ({dep_status})"
                )

    return result


def compute_velocity(sprint_data: dict[str, Any]) -> dict[str, int]:
    """Compute velocity metrics from parsed sprint data.

    Returns dict with stories_planned, stories_delivered, stories_carried.
    """
    sbs = sprint_data["stories_by_status"]
    return {
        "stories_planned": (
            sbs["ready"] + sbs["in_progress"] + sbs["done"] + sbs["deferred"]
        ),
        "stories_delivered": sbs["done"],
        "stories_carried": sbs["deferred"],
    }


def extract_story_sections(content: str | None, story_ids: list[str]) -> str:
    """Extract specific story sections from sprint.md by story ID.

    Returns the matching story sections as markdown text, or empty string
    if no matches found. Used by teammate tier to inject only assigned stories.
    """
    if not content or not story_ids:
        return ""

    wanted = set(story_ids)
    story_starts = list(_STORY_HEADER_RE.finditer(content))
    if not story_starts:
        return ""

    parts: list[str] = []
    for i, match in enumerate(story_starts):
        if match.group(1) in wanted:
            start = match.start()
            if i + 1 < len(story_starts):
                end = story_starts[i + 1].start()
            else:
                end = len(content)
            parts.append(content[start:end].rstrip())

    return "\n\n".join(parts)
