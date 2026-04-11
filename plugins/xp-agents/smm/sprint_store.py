#!/usr/bin/env python3
"""Load/save for sprint.json.

Python API for sprint operations. Pure data store — no acceptance
flow side effects (those stay in save_sprint.py). Internal scripts
import these functions directly. Shell scripts and skills use
sprint_cli.py.

Follows the same pattern as execution_plan_store.py.
"""

import json
from pathlib import Path
from typing import Any

from _append_impl import write_text_atomic
from sprint_schema import (
    SPRINT_FILENAME,
    VALID_STORY_STATUSES,
    validate_sprint,
)

_MARKER_NAME = ".needs-sprint"
_ACTIVE_STATUSES = frozenset({"ready", "in-progress"})

_STATUS_KEY_MAP = {
    "ready": "ready",
    "in-progress": "in_progress",
    "done": "done",
    "deferred": "deferred",
}


def sprint_exists(smm_dir: Path) -> bool:
    """Check if sprint.json exists (not a symlink)."""
    path = smm_dir / SPRINT_FILENAME
    return path.exists() and not path.is_symlink()


def load_sprint(smm_dir: Path) -> dict | None:
    """Read the sprint from disk.

    Returns:
        Parsed sprint dict, or None if file does not exist.

    Raises:
        ValueError: Malformed JSON or schema validation failure.
        OSError: Path is a symlink.
    """
    path = smm_dir / SPRINT_FILENAME
    if path.is_symlink():
        raise OSError(f"Sprint path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt sprint file at {path}: {exc}") from exc

    errors = validate_sprint(data)
    if errors:
        raise ValueError(f"Schema-invalid sprint at {path}: {'; '.join(errors)}")
    return data


def save_sprint(smm_dir: Path, data: dict) -> None:
    """Validate and atomically write the sprint.

    Clears the NEEDS_SPRINT marker if the sprint has active stories.

    Raises:
        ValueError: Schema validation failure.
        OSError: Target is a symlink.
    """
    path = smm_dir / SPRINT_FILENAME
    if path.is_symlink():
        raise OSError(f"Sprint path is a symlink: {path}")

    errors = validate_sprint(data)
    if errors:
        raise ValueError(f"Sprint validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))

    if has_active_stories_data(data):
        (smm_dir / _MARKER_NAME).unlink(missing_ok=True)


def update_story_status(smm_dir: Path, story_id: str, status: str) -> None:
    """Update a story's status in the sprint.

    Raises:
        ValueError: Sprint missing, story not found, or invalid
            status.
    """
    sprint = load_sprint(smm_dir)
    if sprint is None:
        raise ValueError("No sprint found")

    if status not in VALID_STORY_STATUSES:
        valid = sorted(VALID_STORY_STATUSES)
        raise ValueError(f"Invalid status {status!r}, must be one of {valid}")

    matches = [s for s in sprint["stories"] if s["id"] == story_id]
    if not matches:
        raise ValueError(f"No story with id {story_id!r}")

    matches[0]["status"] = status
    save_sprint(smm_dir, sprint)


# -------------------------------------------------------------------
# Status checks (operate on smm_dir, load internally)
# -------------------------------------------------------------------


def has_active_stories(smm_dir: Path) -> bool:
    """True if sprint has ready or in-progress stories."""
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return has_active_stories_data(sprint)


def has_active_stories_data(data: dict) -> bool:
    """True if sprint dict has ready or in-progress stories."""
    return any(s["status"] in _ACTIVE_STATUSES for s in data["stories"])


def has_in_progress_stories(smm_dir: Path) -> bool:
    """True if sprint has in-progress stories."""
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return any(s["status"] == "in-progress" for s in sprint["stories"])


def has_ready_stories(smm_dir: Path) -> bool:
    """True if sprint has ready stories."""
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return any(s["status"] == "ready" for s in sprint["stories"])


def is_complete(smm_dir: Path) -> bool:
    """True when no ready or in-progress stories remain."""
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return True
    if not sprint["stories"]:
        return True
    return not has_active_stories_data(sprint)


# -------------------------------------------------------------------
# Computed fields (pure functions on sprint dict)
# -------------------------------------------------------------------


def count_by_status(sprint: dict) -> dict[str, int]:
    """Count stories by status.

    Returns dict with keys: ready, in_progress, done, deferred.
    """
    counts = {
        "ready": 0,
        "in_progress": 0,
        "done": 0,
        "deferred": 0,
    }
    for s in sprint["stories"]:
        key = _STATUS_KEY_MAP.get(s["status"])
        if key:
            counts[key] += 1
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


# -------------------------------------------------------------------
# Render
# -------------------------------------------------------------------


def render_markdown(sprint: dict) -> str:
    """Render a sprint dict as markdown for display."""
    lines: list[str] = []

    lines.append(f"# Sprint: {sprint['goal']}")
    lines.append("")
    lines.append(f"- **Sprint ID:** {sprint['sprint_id']}")
    lines.append(f"- **Started:** {sprint['started']}")
    if sprint.get("milestone"):
        lines.append(f"- **Milestone:** {sprint['milestone']}")
    lines.append("")

    lines.append("## System Context")
    lines.append("")
    lines.append("See: system_context.md")
    lines.append("")

    lines.append("## Stories")
    lines.append("")

    for s in sprint["stories"]:
        _render_story(lines, s)

    return "\n".join(lines)


def render_story_sections(sprint: dict, story_ids: list[str]) -> str:
    """Render specific story sections as markdown."""
    if not story_ids:
        return ""
    wanted = set(story_ids)
    parts: list[str] = []
    for s in sprint["stories"]:
        if s["id"] in wanted:
            story_lines: list[str] = []
            _render_story(story_lines, s)
            parts.append("\n".join(story_lines))
    return "\n\n".join(parts)


def _render_story(lines: list[str], s: dict[str, Any]) -> None:
    """Render a single story to the lines list."""
    lines.append(f"### {s['id']}: {s['title']}")
    lines.append(f"- **Size:** {s['size']}")
    lines.append(f"- **Status:** {s['status']}")

    deps = ", ".join(s.get("dependencies", [])) or "none"
    lines.append(f"- **Dependencies:** {deps}")

    if s.get("milestone_ref"):
        lines.append(f"- **Milestone:** {s['milestone_ref']}")
    if s.get("design_sources"):
        lines.append(f"- **Design Sources:** {s['design_sources']}")

    if s.get("context"):
        lines.append("")
        lines.append("**Context:**")
        lines.append(s["context"])

    if s.get("file_domain"):
        lines.append("")
        lines.append("**File Domain:**")
        for fd in s["file_domain"]:
            lines.append(f"- {fd}")

    if s.get("interface_contracts"):
        lines.append("")
        lines.append("**Interface Contracts:**")
        for ic in s["interface_contracts"]:
            lines.append(f"- {ic}")

    if s.get("acceptance_criteria"):
        lines.append("")
        lines.append("**Acceptance Criteria:**")
        for ac in s["acceptance_criteria"]:
            lines.append(f"- {ac}")

    lines.append("")
