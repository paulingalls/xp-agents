#!/usr/bin/env python3
"""Load/save for sprint.json.

Python API for sprint operations. Pure data store — no acceptance
flow side effects (those stay in sprint_save.py). Internal scripts
import these functions directly. Shell scripts and skills use
sprint_cli.py.

Follows the same pattern as execution_plan_store.py.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import file_domain_lock
from _append_impl import flock_with_timeout, write_text_atomic
from sprint_schema import (
    SPRINT_FILENAME,
    VALID_STORY_STATUSES,
    validate_sprint,
)
from system_context_store import acceptance_surface_names

_MARKER_NAME = ".needs-sprint"
_SPRINT_LOCK_NAME = "sprint.lock"


class SprintCorruptError(ValueError):
    """Sprint file exists but its content is unusable (malformed JSON or
    schema-invalid) — distinct from a missing sprint/story so callers may
    fail hard on corruption while proceeding on absence. Subclasses
    ValueError so existing `except (ValueError, OSError)` handlers still
    catch it; only a caller that opts in by catching this type first
    changes behavior.
    """


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
        SprintCorruptError: Undecodable bytes, malformed JSON, or schema
            validation failure — the three ways content can be unusable
            (a ValueError subclass — callers that must distinguish a
            corrupt-but-present sprint from absence catch this first).
        OSError: Path is a symlink.
    """
    path = smm_dir / SPRINT_FILENAME
    if path.is_symlink():
        raise OSError(f"Sprint path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        # Bytes that aren't even UTF-8 are corruption, not an OSError — and
        # UnicodeDecodeError is a ValueError, so it would otherwise slip past
        # every `except (SprintCorruptError, OSError)` guard as itself and
        # traceback the caller. Normalize it to the one type those guards catch.
        raise SprintCorruptError(f"Undecodable sprint file at {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SprintCorruptError(f"Corrupt sprint file at {path}: {exc}") from exc

    errors = validate_sprint(data, enforce_budget=False)
    if errors:
        raise SprintCorruptError(
            f"Schema-invalid sprint at {path}: {'; '.join(errors)}"
        )
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

    errors = validate_sprint(
        data,
        enforce_budget=enforce_budget,
        valid_surfaces=(acceptance_surface_names(smm_dir) if enforce_budget else None),
    )
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


def load_sprint_fail_open(smm_dir: Path) -> dict | None:
    """Load the sprint, degrading a corrupt/unreadable file to None.

    For call sites whose read is ADVISORY — the sprint enriches the answer but
    is not required to produce one — so a corrupt file must not crash them. A
    missing OR corrupt sprint collapses to the same None. Sibling of
    `load_sprint_required`: same load_sprint core, opposite posture on the
    must/may-exist axis. Two families qualify, and a new caller must argue it
    into one of them or use `load_sprint` and stay loud:

    - Post-merge accounting (trailer_gate, merge_commit_event, close_common's
      merge helpers): the merge already committed, so an SMM-state problem must
      never crash the close chain.
    - Reads whose degraded answer is SAFE and whose loudness is delegated to a
      later, stricter step (sprint_save.introduced_collisions — losing the
      baseline attributes EVERY collision to this write, making the gate
      stricter; branching._recorded_sprint_branch — runs below the stage gate,
      and set_branch re-raises on the same corruption once a branch is cut;
      spawn_teammate.resolve_sprint_id — the sprint only NAMESPACES the teammate
      prompt/log path, and it degrades to the project-only namespace identically
      for the path query and for the spawn that reads the file back, so the two
      still meet at one path; the stale-prompt refusal downstream stays loud
      however the path resolved). The first two also keep `sprint_cli create`
      the repair path for a sprint.json that no longer loads; a hard raise in
      either bricks it.
    """
    try:
        return load_sprint(smm_dir)
    except (SprintCorruptError, OSError):
        return None


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
    # Gate collision-relevant edits through run()'s shared this-write-only
    # attribution (introduced_collisions sister-expands + reports both sides).
    # A file_domain change can reintroduce a collision M1 forbids, and a
    # dependency change can make two shared-path stories concurrent — both are
    # gated here. (collision_report also reads `status` via concurrency, but
    # status flips route through update_story_status, not edit_story, and that
    # path is itself ungated by design — so status is out of scope here.) Other
    # edits (execution_mode, executor_model, context, …) can't affect collisions
    # and skip the sister-expansion cost.
    if updates.keys() & {"file_domain", "dependencies"}:
        import sprint_save  # function-local: sprint_save imports sprint_store (cycle)

        introduced = sprint_save.introduced_collisions(sprint, smm_dir)
        if introduced:
            raise ValueError(file_domain_lock.format_collision_report(introduced))
    save_sprint(smm_dir, sprint)


# -------------------------------------------------------------------
# Ready frontier + dependency queries — re-exported from sprint_frontier
# -------------------------------------------------------------------
# Bodies live in sprint_frontier.py; this block keeps the historical
# `from sprint_store import ready_frontier` import path working.
from sprint_frontier import (  # noqa: E402  intentional mid-file re-export
    next_in_progress_story_id,
    next_scheduled_story_id,
    ready_frontier,
    ready_frontier_data,
    ready_frontier_report,
    transitive_active_dependents,
)

# -------------------------------------------------------------------
# Computed fields — re-exported from sprint_metrics
# -------------------------------------------------------------------
# Bodies live in sprint_metrics.py; this block keeps the historical
# `from sprint_store import compute_velocity` import path working.
from sprint_metrics import (  # noqa: E402  intentional mid-file re-export
    compute_blockers,
    compute_velocity,
    count_by_status,
    list_stories,
    next_sprint_id,
)

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
    in_progress_is_teammate,
    in_progress_is_teammate_data,
    is_complete,
    schedule_gate_active,
    schedule_gate_active_data,
    select_closing_stories,
    select_in_motion_stories,
)

# Public API contract — listed for pyright (so re-exports aren't flagged
# "not accessed") and ruff F401 suppression without per-line noqa. Must
# enumerate ALL public names of this module, both module-defined and
# re-exported, to be a complete contract.
__all__ = [
    "SprintCorruptError",
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
    "in_progress_is_teammate",
    "in_progress_is_teammate_data",
    "is_complete",
    "list_stories",
    "load_sprint",
    "load_sprint_fail_open",
    "load_sprint_required",
    "next_in_progress_story_id",
    "next_scheduled_story_id",
    "next_sprint_id",
    "ready_frontier",
    "ready_frontier_data",
    "ready_frontier_report",
    "save_sprint",
    "schedule_gate_active",
    "schedule_gate_active_data",
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

    Branch-existence check: a non-empty branch_name means the branch
    already exists (a parallel teammate batch created at /xp-assign), so
    creation is skipped. Empty means none yet. Branch creation lives in
    /xp-schedule (solo, JIT off the sprint tip) and /xp-assign (teammate).

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
    harness: str | None = None,
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

    ``harness`` is the resolved ``acceptance_execution.type``. It is
    never guessed here — callers resolve it (e.g. from the project's
    declared acceptance surfaces) and pass it in, or pass ``None`` when
    no harness could be resolved. ``None`` yields a schema-valid
    placeholder type rather than an omitted field, so the capstone stays
    in the acceptance roll-up until an implementer fills it in.
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
            "type": harness or "<implementer fills: test harness>",
            "command": "<implementer fills: cross-cutting test invocation>",
            "notes": "Placeholder — fill with the real cross-cutting test command.",
        },
    }
