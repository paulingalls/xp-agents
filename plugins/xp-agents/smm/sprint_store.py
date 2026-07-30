#!/usr/bin/env python3
"""Load/save for sprint.json.

Python API for sprint operations. Pure data store — no acceptance
flow side effects (those stay in sprint_save.py). Internal scripts
import these functions directly. Shell scripts and skills use
sprint_cli.py.

Follows the same pattern as execution_plan_store.py.
"""

import json
from pathlib import Path

import file_domain_lock
from _append_impl import write_text_atomic
from _manual_shape_exemption import grandfathered_story_ids
from sprint_schema import (
    SPRINT_FILENAME,
    validate_sprint,
)
from system_context_store import acceptance_surface_names

_MARKER_NAME = ".needs-sprint"


class SprintCorruptError(ValueError):
    """Sprint file exists but its content is unusable (malformed JSON or
    schema-invalid) — distinct from a missing sprint/story so callers may
    fail hard on corruption while proceeding on absence. Subclasses
    ValueError so existing `except (ValueError, OSError)` handlers still
    catch it; only a caller that opts in by catching this type first
    changes behavior.
    """


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

    Every write applies the manual-acceptance-shape rule, exempting only
    blocks already on disk (see _manual_shape_exemption).

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
        grandfathered_story_ids=grandfathered_story_ids(smm_dir, data),
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


# `id` is immutable outright. `status` is not immutable — it is TRANSITIONED, and a
# shallow-merge patch is not a transition: it walks around the state machine that owns
# the field (update_story_status / update_story_status_if) and around the merge gate
# standing at its `done` edge, so `{"status":"done"}` forges a ship nobody proved. Same
# hole plan_cli.edit-milestone closes for status/delivered_sprint, same answer.
_IMMUTABLE_STORY_FIELDS = frozenset({"id"})
_TRANSITION_ONLY_STORY_FIELDS = frozenset({"status"})


def edit_story(smm_dir: Path, story_id: str, updates: object) -> None:
    """Shallow-merge updates into a story's fields.

    `updates` is typed as `object` (not `dict`) because the CLI caller
    forwards raw `json.loads` output, which can legally be a list,
    scalar, or null. The isinstance check is a real boundary guard.
    Refuses `status` — see _TRANSITION_ONLY_STORY_FIELDS.
    """
    if not isinstance(updates, dict):
        raise ValueError("updates must be a JSON object")
    protected = _IMMUTABLE_STORY_FIELDS & updates.keys()
    if protected:
        raise ValueError(f"Cannot edit immutable fields: {sorted(protected)}")
    transitional = _TRANSITION_ONLY_STORY_FIELDS & updates.keys()
    if transitional:
        raise ValueError(
            f"edit-story may not patch {', '.join(sorted(transitional))} — use "
            "update-story / update-story-if, which the merge gate stands on."
        )

    sprint, story = _load_story(smm_dir, story_id)
    story.update(updates)
    # Gate collision-relevant edits through run()'s shared this-write-only
    # attribution (introduced_collisions sister-expands + reports both sides).
    # A file_domain change can reintroduce a collision M1 forbids, and a
    # dependency change can make two shared-path stories concurrent — both are
    # gated here. (collision_report also reads `status` via concurrency, but
    # this path can no longer write status at all — see the refusal above.) Other
    # edits (execution_mode, executor_model, context, …) can't affect collisions
    # and skip the sister-expansion cost.
    #
    # running_only=True: this is a MID-SPRINT amendment, so the question is
    # whether a path is claimed by a story that is actually running, not by one
    # that was merely planned. A parked story's claim vetoing a live story's
    # amendment was the measured bug. run() keeps the strict default — see
    # sprint_save.introduced_collisions.
    if updates.keys() & {"file_domain", "dependencies"}:
        import sprint_save  # function-local: sprint_save imports sprint_store (cycle)

        introduced = sprint_save.introduced_collisions(
            sprint, smm_dir, running_only=True
        )
        if introduced:
            raise ValueError(file_domain_lock.format_collision_report(introduced))
    save_sprint(smm_dir, sprint)


# -------------------------------------------------------------------
# Capstone story builder — re-exported from sprint_capstone
# -------------------------------------------------------------------
# Body lives in sprint_capstone.py (pure, no I/O); this block keeps the
# historical `from sprint_store import build_capstone_story` import path
# working for sprint_cli_mutate and the tests.
from sprint_capstone import (  # noqa: E402  intentional mid-file re-export
    build_capstone_story,
)

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
    select_promoted_teammate_stories,
)

# -------------------------------------------------------------------
# Status transitions — re-exported from sprint_transitions
# -------------------------------------------------------------------
# Bodies live in sprint_transitions.py; this block keeps the historical
# `from sprint_store import update_story_status` import path working. Both
# writers share one locked helper there, so a caller cannot reach the status
# machine by a route the start-time collision check does not cover.
from sprint_transitions import (  # noqa: E402  intentional mid-file re-export
    update_story_status,
    update_story_status_if,
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
    "select_promoted_teammate_stories",
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
