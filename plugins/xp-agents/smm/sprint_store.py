#!/usr/bin/env python3
"""Load/save for sprint.json.

Python API for sprint operations. Pure data store — no acceptance
flow side effects (those stay in save_sprint.py). Internal scripts
import these functions directly. Shell scripts and skills use
sprint_cli.py.

Follows the same pattern as execution_plan_store.py.
"""

import json
import sys
from pathlib import Path
from typing import Any

from _acceptance_execution import render_acceptance_execution
from _append_impl import write_text_atomic
from sprint_schema import (
    SPRINT_FILENAME,
    VALID_STORY_STATUSES,
    validate_sprint,
)

_MARKER_NAME = ".needs-sprint"


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

    errors = validate_sprint(data, enforce_budget=False)
    if errors:
        raise ValueError(f"Schema-invalid sprint at {path}: {'; '.join(errors)}")
    return data


def save_sprint(smm_dir: Path, data: dict, *, enforce_budget: bool = True) -> None:
    """Validate and atomically write the sprint.

    Clears the NEEDS_SPRINT marker if the sprint has active stories.

    Raises:
        ValueError: Schema validation failure.
        OSError: Target is a symlink.
    """
    path = smm_dir / SPRINT_FILENAME
    if path.is_symlink():
        raise OSError(f"Sprint path is a symlink: {path}")

    errors = validate_sprint(data, enforce_budget=enforce_budget)
    if errors:
        raise ValueError(f"Sprint validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))

    if has_active_stories_data(data):
        (smm_dir / _MARKER_NAME).unlink(missing_ok=True)


def _load_required(smm_dir: Path) -> dict:
    """Load the sprint or raise ValueError if missing."""
    sprint = load_sprint(smm_dir)
    if sprint is None:
        raise ValueError("No sprint found")
    return sprint


def _load_story(smm_dir: Path, story_id: str) -> tuple[dict, dict]:
    """Load sprint and find story by ID. Returns (sprint, story) refs."""
    sprint = _load_required(smm_dir)
    matches = [s for s in sprint["stories"] if s["id"] == story_id]
    if not matches:
        raise ValueError(f"No story with id {story_id!r}")
    return sprint, matches[0]


def get_story(smm_dir: Path, story_id: str) -> dict:
    """Return the story dict by id. Raises ValueError if missing."""
    _, story = _load_story(smm_dir, story_id)
    return story


def update_story_status(smm_dir: Path, story_id: str, status: str) -> None:
    """Update a story's status in the sprint."""
    if status not in VALID_STORY_STATUSES:
        valid = sorted(VALID_STORY_STATUSES)
        raise ValueError(f"Invalid status {status!r}, must be one of {valid}")

    sprint, story = _load_story(smm_dir, story_id)
    story["status"] = status
    save_sprint(smm_dir, sprint, enforce_budget=False)


def set_branch(smm_dir: Path, branch_name: str) -> None:
    """Record the sprint's git branch name."""
    sprint = _load_required(smm_dir)
    sprint["branch_name"] = branch_name
    save_sprint(smm_dir, sprint, enforce_budget=False)


def set_story_branch(smm_dir: Path, story_id: str, branch_name: str) -> None:
    """Record a story's git branch name."""
    sprint, story = _load_story(smm_dir, story_id)
    story["branch_name"] = branch_name
    save_sprint(smm_dir, sprint, enforce_budget=False)


_IMMUTABLE_STORY_FIELDS = frozenset({"id"})


def edit_story(smm_dir: Path, story_id: str, updates: object) -> None:
    """Shallow-merge updates into a story's fields.

    `updates` is typed as `object` (not `dict`) because the CLI caller
    forwards raw `json.loads` output, which can legally be a list,
    scalar, or null. The isinstance check is a real boundary guard.
    """
    if not isinstance(updates, dict):
        raise ValueError("updates must be a JSON object")
    protected = _IMMUTABLE_STORY_FIELDS & updates.keys()
    if protected:
        raise ValueError(f"Cannot edit immutable fields: {sorted(protected)}")

    sprint, story = _load_story(smm_dir, story_id)
    story.update(updates)
    save_sprint(smm_dir, sprint)


# -------------------------------------------------------------------
# Status checks — re-exported from sprint_status (story-008 split)
# -------------------------------------------------------------------
# Bodies live in sprint_status.py; this block keeps the historical
# `from sprint_store import has_active_stories` import path working for
# every caller (production scripts and 16+ test files).

from sprint_status import (  # noqa: E402  intentional mid-file re-export
    has_active_stories,  # noqa: F401  re-export for legacy callers
    has_active_stories_data,
    has_in_progress_stories,  # noqa: F401  re-export for legacy callers
    has_ready_stories,  # noqa: F401  re-export for legacy callers
    has_scheduled_stories,  # noqa: F401  re-export for legacy callers
    has_stories_with_status,  # noqa: F401  re-export for legacy callers
    is_complete,  # noqa: F401  re-export for legacy callers
    scheduled_file_domains_overlap,  # noqa: F401  re-export for legacy callers
)


def get_story_branch_name(smm_dir: Path, story_id: str) -> str:
    """Return the recorded branch_name for a story, or empty string.

    Powers /xp-story-close's JIT-next gate: a non-empty branch_name
    means the branch already exists (parallel teammate batch at
    /xp-assign), so JIT-create is skipped. Empty means solo mode —
    create the branch off the just-merged sprint tip.

    Returns "" when the sprint is missing OR the story is missing OR
    branch_name is unset, to keep the CLI contract simple (caller can
    test for non-empty without distinguishing the failure modes).
    """
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return ""
    story = next((s for s in sprint["stories"] if s["id"] == story_id), None)
    if story is None:
        return ""
    return story.get("branch_name", "") or ""


def _next_story_id_with_status(smm_dir: Path, status: str) -> str | None:
    """Lowest-id story with `status` whose deps are ALL done. None if none.

    Powers JIT branch creation in /xp-story-close: the next story's
    branch is born off the merged tip of the just-accepted story, but
    only when the candidate's deps are actually satisfied. Cascade-defer
    naturally excludes blocked stories — a deferred story's status is
    "deferred", not "done", so any matching story depending on it fails
    the "all deps done" check and is skipped.
    """
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return None
    by_id = {s["id"]: s for s in sprint["stories"]}

    def _deps_done(story: dict) -> bool:
        return all(
            by_id.get(dep, {}).get("status") == "done"
            for dep in story.get("dependencies", [])
        )

    eligible = [
        s["id"] for s in sprint["stories"] if s["status"] == status and _deps_done(s)
    ]
    if not eligible:
        return None

    # Numeric sort by trailing -NNN — lexical min would order story-10
    # before story-2. Project convention zero-pads (story-001) but a
    # numeric key removes the latent footgun. Malformed ids (typos
    # like `story-2a` that escaped schema validation) fall back to a
    # large sentinel so they sort last instead of crashing the close
    # pipeline with an uncaught ValueError.
    def _id_sort_key(s: str) -> tuple[int, str]:
        tail = s.rsplit("-", 1)[-1]
        try:
            return (int(tail), s)
        except ValueError:
            return (sys.maxsize, s)

    return min(eligible, key=_id_sort_key)


def next_in_progress_story_id(smm_dir: Path) -> str | None:
    """Lowest-id in-progress story whose deps are ALL done. None if none.

    Powers /xp-story-close's JIT branch creation: the next story's branch
    is born off the merged tip of the just-accepted story, but only when
    its deps are actually satisfied. Cascade-defer naturally excludes
    blocked stories — a deferred story's status is "deferred", not
    "done", so any in-progress story depending on it fails the
    "all deps done" check and is skipped.
    """
    return _next_story_id_with_status(smm_dir, "in-progress")


def next_scheduled_story_id(smm_dir: Path) -> str | None:
    """Lowest-id scheduled story whose deps are ALL done. None if none.

    Powers /xp-story-close's JIT-next dispatch when no in-progress story
    remains: promotes the next scheduled story to in-progress + creates
    its branch off the merged sprint tip. Same cascade-defer semantics
    as next_in_progress_story_id.
    """
    return _next_story_id_with_status(smm_dir, "scheduled")


# -------------------------------------------------------------------
# Computed fields (pure functions on sprint dict)
# -------------------------------------------------------------------


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
    """Determine the next sprint ID.

    Fast path: increments the number in the current sprint_id.
    Fallback: counts sprint start events in events.jsonl.
    Default: 'sprint-001' if no history exists.
    """
    sprint = load_sprint(smm_dir)
    if sprint is not None and sprint["sprint_id"]:
        sid = sprint["sprint_id"]
        parts = sid.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            num = int(parts[1]) + 1
            return f"{parts[0]}-{num:03d}"

    # Fallback: count sprint start events in the event log
    count = _count_sprint_starts(smm_dir)
    return f"sprint-{count + 1:03d}"


def _count_sprint_starts(smm_dir: Path) -> int:
    """Count sprint start events in events.jsonl."""
    from append_validation import parse_jsonl

    path = smm_dir / "events.jsonl"
    if path.is_symlink():
        return 0
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return 0
    events, _ = parse_jsonl(raw)
    return sum(
        1
        for e in events
        if e.get("type") == "sprint"
        and (e.get("metadata") or {}).get("action") == "start"
    )


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
    lines.append("See: system_context.json")
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

    ae = s.get("acceptance_execution")
    if ae:
        lines.append("")
        render_acceptance_execution(ae, lines)

    lines.append("")
