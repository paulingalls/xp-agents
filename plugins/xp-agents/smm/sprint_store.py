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
from itertools import combinations
from pathlib import Path

from _append_impl import write_text_atomic
from sprint_schema import (
    ACTIVE_STORY_STATUSES,
    SPRINT_FILENAME,
    VALID_STORY_STATUSES,
    validate_sprint,
)
from triage import extract_file_domain_paths

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
    return any(s["status"] in ACTIVE_STORY_STATUSES for s in data["stories"])


def has_stories_with_status(smm_dir: Path, status: str) -> bool:
    """True if sprint has any story matching `status`."""
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return any(s["status"] == status for s in sprint["stories"])


def has_in_progress_stories(smm_dir: Path) -> bool:
    """True if sprint has in-progress stories."""
    return has_stories_with_status(smm_dir, "in-progress")


def has_ready_stories(smm_dir: Path) -> bool:
    """True if sprint has ready stories."""
    return has_stories_with_status(smm_dir, "ready")


def has_scheduled_stories(smm_dir: Path) -> bool:
    """True if sprint has scheduled stories (queued for this iteration)."""
    return has_stories_with_status(smm_dir, "scheduled")


def scheduled_file_domains_overlap(smm_dir: Path) -> bool:
    """True when 2+ scheduled stories share at least one file in their
    file_domain.

    Powers /xp-assign's auto-pick-solo decision: if any scheduled stories'
    file_domains overlap, parallel teammates would step on each other —
    auto-pick solo without asking the user. Returns False when fewer than
    two scheduled stories exist (no pair to overlap).

    Reuses the canonical em-dash splitter from `triage` so parsing matches
    every other consumer of file_domain entries (paths with embedded
    whitespace work correctly; descriptions don't mask shared files).
    """
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    scheduled = [s for s in sprint["stories"] if s.get("status") == "scheduled"]
    if len(scheduled) < 2:
        return False

    path_sets = [
        extract_file_domain_paths(s.get("file_domain") or []) for s in scheduled
    ]
    return any(a & b for a, b in combinations(path_sets, 2))


def is_complete(smm_dir: Path) -> bool:
    """True when no ready or in-progress stories remain."""
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return True
    if not sprint["stories"]:
        return True
    return not has_active_stories_data(sprint)


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


def transitive_in_progress_dependents(smm_dir: Path, story_id: str) -> list[str]:
    """In-progress stories that depend (transitively) on `story_id`, sorted.

    Powers cascade-deferral in /xp-accept: when a story can't ship, every
    in-progress descendant is also blocked and should be deferred together.
    Done dependents are excluded — they already shipped — and a self-loop
    or A↔B cycle terminates because we only add unseen ids.
    """
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return []

    blocked = {story_id}
    changed = True
    while changed:
        changed = False
        for s in sprint["stories"]:
            if s.get("status") != "in-progress":
                continue
            sid = s.get("id")
            if not sid or sid in blocked:
                continue
            if any(d in blocked for d in s.get("dependencies", [])):
                blocked.add(sid)
                changed = True
    return sorted(blocked - {story_id})


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
# Render — moved to sprint_render.py at the commit that pushed this file
# over the 500-line cap. Re-exported here so callers don't break; new
# imports should target sprint_render directly.
# -------------------------------------------------------------------


from sprint_render import render_markdown, render_story_sections  # noqa: E402, F401
