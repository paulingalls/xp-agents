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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from _append_impl import flock_with_timeout, write_text_atomic
from sprint_schema import (
    IN_MOTION_STORY_STATUSES,
    SPRINT_FILENAME,
    VALID_STORY_STATUSES,
    validate_sprint,
)

_MARKER_NAME = ".needs-sprint"
_SPRINT_LOCK_NAME = "sprint.lock"


@contextmanager
def _sprint_lock(smm_dir: Path) -> Iterator[None]:
    """Hold an exclusive flock on sprint.lock for the duration of the block.

    Used by update_story_status_if to make the load-check-write CAS one
    indivisible critical section — a second CAS caller racing this one
    will see the post-update state when its load runs, not the pre-update
    snapshot. The shared `flock_with_timeout` helper provides the
    SIGALRM-bounded acquire and suppress-OSError-on-release semantics
    so a deadlocked sibling can't wedge the wrapper.

    Other unlocked sprint mutators (update_story_status, set_branch, etc.)
    do NOT take this lock — the CAS only guarantees atomicity against
    other CAS callers. Closing the in-process get→update window in
    spawn_teammate.py is the load-bearing fix; cross-process protection
    against unlocked writers is out of scope for this wrapper.
    """
    with flock_with_timeout(smm_dir / _SPRINT_LOCK_NAME):
        yield


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


def load_sprint_required(smm_dir: Path) -> dict:
    """Load the sprint or raise ValueError if missing.

    Use this at call sites where the sprint MUST exist (CLI commands,
    tests with seeded fixtures). Pyright sees the `dict` return so
    callers don't need a follow-up `assert sprint is not None`.
    """
    sprint = load_sprint(smm_dir)
    if sprint is None:
        raise ValueError(f"No sprint found at {smm_dir}")
    return sprint


def _load_story(smm_dir: Path, story_id: str) -> tuple[dict, dict]:
    """Load sprint and find story by ID. Returns (sprint, story) refs."""
    sprint = load_sprint_required(smm_dir)
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


def update_story_status_if(
    smm_dir: Path, story_id: str, *, expected: str, new: str
) -> bool:
    """Atomic compare-and-swap on story status.

    Returns True when the on-disk status matched ``expected`` and the
    write to ``new`` succeeded; False when the status differed (no-op,
    file untouched). Raises ValueError for an unknown ``new`` status,
    a missing story id, or a missing sprint.

    Closes the get_story → update_story_status TOCTOU window in
    spawn_teammate.py: the load-check-write runs under one flock so
    a story already advanced past ``expected`` (e.g. an orchestrator
    flipped it to ``done``) cannot be silently demoted.
    """
    if new not in VALID_STORY_STATUSES:
        valid = sorted(VALID_STORY_STATUSES)
        raise ValueError(f"Invalid status {new!r}, must be one of {valid}")

    with _sprint_lock(smm_dir):
        sprint, story = _load_story(smm_dir, story_id)
        if story["status"] != expected:
            return False
        story["status"] = new
        save_sprint(smm_dir, sprint, enforce_budget=False)
        return True


def set_branch(smm_dir: Path, branch_name: str) -> None:
    """Record the sprint's git branch name."""
    sprint = load_sprint_required(smm_dir)
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
# Status checks — re-exported from sprint_status
# -------------------------------------------------------------------
# Bodies live in sprint_status.py; this block keeps the historical
# `from sprint_store import has_active_stories` import path working for
# every caller (production scripts and 16+ test files).

from sprint_status import (  # noqa: E402  intentional mid-file re-export
    has_active_stories,
    has_active_stories_data,
    has_closing_stories,
    has_closing_stories_data,
    has_in_motion_stories,
    has_in_motion_stories_data,
    has_in_progress_stories,
    has_in_progress_stories_data,
    has_ready_stories,
    has_reviewing_stories,
    has_reviewing_stories_data,
    has_scheduled_stories,
    has_stories_with_status,
    has_stories_with_status_data,
    has_under_acceptance_stories,
    has_under_acceptance_stories_data,
    is_complete,
    scheduled_file_domains_overlap,
    select_closing_stories,
    select_in_motion_stories,
)

# Public API contract — listed for pyright (so re-exports aren't flagged
# "not accessed") and ruff F401 suppression without per-line noqa. Must
# enumerate ALL public names of this module, both module-defined and
# re-exported, to be a complete contract.
__all__ = [
    "build_capstone_story",
    "compute_blockers",
    "compute_velocity",
    "count_by_status",
    "edit_story",
    "get_story",
    "get_story_branch_name",
    "has_active_stories",
    "has_active_stories_data",
    "has_closing_stories",
    "has_closing_stories_data",
    "has_in_motion_stories",
    "has_in_motion_stories_data",
    "has_in_progress_stories",
    "has_in_progress_stories_data",
    "has_ready_stories",
    "has_reviewing_stories",
    "has_reviewing_stories_data",
    "has_scheduled_stories",
    "has_stories_with_status",
    "has_stories_with_status_data",
    "has_under_acceptance_stories",
    "has_under_acceptance_stories_data",
    "is_complete",
    "list_stories",
    "load_sprint",
    "load_sprint_required",
    "next_in_progress_story_id",
    "next_scheduled_story_id",
    "next_sprint_id",
    "save_sprint",
    "scheduled_file_domains_overlap",
    "select_closing_stories",
    "select_in_motion_stories",
    "set_branch",
    "set_story_branch",
    "sprint_exists",
    "transitive_active_dependents",
    "update_story_status",
    "update_story_status_if",
]


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


def _next_story_id_with_status(
    smm_dir: Path,
    status: str,
    *,
    treat_as_done: set[str] | None = None,
) -> str | None:
    """Lowest-id story with `status` whose deps are ALL done. None if none.

    Powers JIT branch creation in /xp-story-close: the next story's
    branch is born off the merged tip of the just-accepted story, but
    only when the candidate's deps are actually satisfied. Cascade-defer
    naturally excludes blocked stories — a deferred story's status is
    "deferred", not "done", so any matching story depending on it fails
    the "all deps done" check and is skipped.

    `treat_as_done` lets the caller assert "this id is about to be
    done" without it actually being marked done on disk yet. Closes
    the JIT-next race: /xp-story-close Step 8 runs BEFORE /xp-accept
    Step 4 marks the just-closed story `done`, so a dep-gated next
    story would never be promoted in solo mode without this override.
    """
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return None
    by_id = {s["id"]: s for s in sprint["stories"]}
    overrides = treat_as_done or set()

    def _deps_done(story: dict) -> bool:
        return all(
            (dep in overrides) or by_id.get(dep, {}).get("status") == "done"
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


def transitive_active_dependents(smm_dir: Path, story_id: str) -> list[str]:
    """In-motion stories that depend (transitively) on `story_id`, sorted.

    Powers cascade-deferral in /xp-accept: when a story can't ship, every
    in-motion descendant is also blocked and should be deferred together.
    In-motion = in-progress OR reviewing OR closing (see sprint_schema's
    IN_MOTION_STORY_STATUSES) — a reviewing/closing dependent is mid-
    acceptance or mid-close and its verification work is invalidated when
    its base defers. Done/deferred/ready/scheduled dependents are excluded;
    cycles terminate because we only add unseen ids.
    """
    sprint = load_sprint(smm_dir)
    if sprint is None:
        return []

    blocked = {story_id}
    changed = True
    while changed:
        changed = False
        for s in sprint["stories"]:
            if s.get("status") not in IN_MOTION_STORY_STATUSES:
                continue
            sid = s.get("id")
            if not sid or sid in blocked:
                continue
            if any(d in blocked for d in s.get("dependencies", [])):
                blocked.add(sid)
                changed = True
    return sorted(blocked - {story_id})


def next_in_progress_story_id(
    smm_dir: Path, *, treat_as_done: set[str] | None = None
) -> str | None:
    """Lowest-id in-progress story whose deps are ALL done. None if none.

    Powers /xp-story-close's JIT branch creation: the next story's branch
    is born off the merged tip of the just-accepted story, but only when
    its deps are actually satisfied. Cascade-defer naturally excludes
    blocked stories — a deferred story's status is "deferred", not
    "done", so any in-progress story depending on it fails the
    "all deps done" check and is skipped.

    See `_next_story_id_with_status` for the `treat_as_done` override
    semantics — exposed here for symmetry with `next_scheduled_story_id`.
    """
    return _next_story_id_with_status(
        smm_dir, "in-progress", treat_as_done=treat_as_done
    )


def next_scheduled_story_id(
    smm_dir: Path, *, treat_as_done: set[str] | None = None
) -> str | None:
    """Lowest-id scheduled story whose deps are ALL done. None if none.

    Powers /xp-story-close's JIT-next dispatch when no in-progress story
    remains: promotes the next scheduled story to in-progress + creates
    its branch off the merged sprint tip. Same cascade-defer semantics
    as next_in_progress_story_id.
    """
    return _next_story_id_with_status(smm_dir, "scheduled", treat_as_done=treat_as_done)


# -------------------------------------------------------------------
# Capstone story builder (pure — no I/O)
# -------------------------------------------------------------------


def build_capstone_story(
    story_id: str,
    milestone_name: str,
    touched_surfaces: list[str],
    depends_on: list[str],
    *,
    milestone_ref: str = "",
    harness: str = "pytest",
) -> dict:
    """Return a schema-valid capstone story dict for a milestone.

    The capstone is the final story: it depends on every sibling and
    proves the milestone's surfaces compose end to end. Each touched
    surface becomes one behavior-shaped object AC (`{description,
    surface}`); a cross-surface ``E2E:`` AC heads the list. The
    ``acceptance_execution`` block is a non-empty placeholder the
    implementer replaces with the real cross-cutting invocation when the
    capstone's own story is built. Pure: the caller appends the result
    to the stories list and persists via ``save_sprint``.
    """
    acceptance_criteria: list[str | dict] = [
        f"E2E: Given the {milestone_name} stories ship, When the cross-cutting "
        f"acceptance test exercises every touched surface, Then all report green"
    ]
    for surface in touched_surfaces:
        acceptance_criteria.append(
            {
                "description": (
                    f"Given the {milestone_name} stories ship, When the {surface} "
                    f"acceptance suite runs, Then it passes"
                ),
                "surface": surface,
            }
        )

    return {
        "id": story_id,
        "title": f"Capstone: {milestone_name}",
        "status": "ready",
        "dependencies": list(depends_on),
        "milestone_ref": milestone_ref,
        "design_sources": "",
        "context": (
            f"Capstone for {milestone_name}: cross-cutting acceptance test "
            f"proving the milestone's surfaces compose end to end."
        ),
        "file_domain": [
            "<implementer fills: cross-cutting acceptance test path>",
        ],
        "interface_contracts": [],
        "acceptance_criteria": acceptance_criteria,
        "acceptance_execution": {
            "type": harness,
            "command": "<implementer fills: cross-cutting test invocation>",
            "notes": "Placeholder — fill with the real cross-cutting test command.",
        },
    }


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
