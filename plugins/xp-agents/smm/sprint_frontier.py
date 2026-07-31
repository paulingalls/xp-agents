#!/usr/bin/env python3
"""Ready-frontier and dependency-query helpers for sprint.json.

Extracted from sprint_store.py once that module crossed 500 lines.
sprint_store re-exports every name defined here so existing call sites
(`from sprint_store import ready_frontier`) keep working.

`load_sprint` is imported lazily inside each function so this module can
import cleanly without a cycle when sprint_store re-exports back.
"""

import sys
from pathlib import Path

import file_domain_lock
from sprint_schema import IN_MOTION_STORY_STATUSES
from sprint_status import file_domains_overlap_detail


def _story_id_sort_key(story_id: str) -> tuple[int, str]:
    """Numeric sort by trailing -NNN — lexical would order story-10 before
    story-2. Project convention zero-pads (story-001) but the numeric key
    removes the latent footgun. Malformed ids (typos like `story-2a` that
    escaped schema validation) fall back to a large sentinel so they sort
    last instead of crashing the close pipeline with an uncaught ValueError.
    """
    tail = story_id.rsplit("-", 1)[-1]
    try:
        return (int(tail), story_id)
    except ValueError:
        return (sys.maxsize, story_id)


def _deps_satisfied(story: dict, by_id: dict, overrides: set[str]) -> bool:
    """True when every dep is `done` (or asserted via `overrides`).

    `overrides` (treat_as_done) lets a caller assert "this id is about to
    be done" without it being marked done on disk yet — e.g. a promotion
    query that runs while the just-closed story is still `closing`.
    Cascade-defer falls out naturally: a deferred dep's status is
    "deferred", not "done", so dependents fail the check and are skipped.
    """
    return all(
        (dep in overrides) or by_id.get(dep, {}).get("status") == "done"
        for dep in story.get("dependencies", [])
    )


def _eligible_sorted_ids(data: dict, status: str, overrides: set[str]) -> list[str]:
    """Stories with `status` whose deps are all satisfied, sorted by id."""
    by_id = {s["id"]: s for s in data["stories"]}
    eligible = [
        s["id"]
        for s in data["stories"]
        if s["status"] == status and _deps_satisfied(s, by_id, overrides)
    ]
    return sorted(eligible, key=_story_id_sort_key)


def _next_story_id_with_status(
    smm_dir: Path,
    status: str,
    *,
    treat_as_done: set[str] | None = None,
) -> str | None:
    """Lowest-id story with `status` whose deps are ALL done. None if none.

    Backs the `next-in-progress` sprint_cli query — surfaces the next
    dep-satisfied story for promotion/branching, which /xp-schedule owns
    (off the merged sprint tip), only when the candidate's deps are
    actually satisfied.

    See `_deps_satisfied` for the `treat_as_done` override semantics.
    """
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return None
    eligible = _eligible_sorted_ids(sprint, status, treat_as_done or set())
    return eligible[0] if eligible else None


def ready_frontier_data(
    data: dict, *, treat_as_done: set[str] | None = None
) -> list[str]:
    """The ready frontier from a loaded sprint dict (pure).

    The frontier /xp-schedule promotes: dep-satisfied `scheduled` stories,
    sorted by id. Lifecycle is ready→scheduled (work-selection)→in-progress
    (/xp-schedule), so the frontier is over `scheduled`, not `ready`. Sibling
    to `ready_frontier` for callers that already hold the sprint dict.
    """
    return _eligible_sorted_ids(data, "scheduled", treat_as_done or set())


def ready_frontier(
    smm_dir: Path, *, treat_as_done: set[str] | None = None
) -> list[str]:
    """The ready frontier: dep-satisfied `scheduled` stories, sorted by id.

    Consumed by skills/xp-schedule/preload.sh to decide solo vs parallel.
    Empty list when no sprint or no eligible scheduled story. See
    `_deps_satisfied` for the `treat_as_done` override.
    """
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return []
    return ready_frontier_data(sprint, treat_as_done=treat_as_done)


def _frontier_has_internal_dependency(data: dict, frontier: list[str]) -> bool:
    """True when some frontier member transitively depends on another.

    A promoted frontier is supposed to be an antichain: every member cut to
    its own branch off the SAME sprint base, safe to run concurrently. A
    dependency edge between two frontier members — direct OR transitive,
    and possibly running through a story that is itself absent from the
    frontier — breaks that: the dependent would be branched without its
    dependency's commits regardless of whether their file domains overlap.
    `file_domain_lock.ancestors` is the existing fixed-point, cycle-safe
    transitive closure over the full sprint's dependency graph (not just the
    frontier subset), so a dependency reached through a non-frontier story
    is still found.
    """
    story_ancestors = file_domain_lock.ancestors(data["stories"])
    members = set(frontier)
    return any(story_ancestors.get(sid, set()) & (members - {sid}) for sid in frontier)


def ready_frontier_report(
    smm_dir: Path, *, treat_as_done: set[str] | None = None
) -> dict:
    """The ready frontier plus its parallelizable verdict and overlap detail.

    Returns ``{"frontier": [ids...], "parallelizable": bool, "overlap": {...}}``
    for the /xp-schedule preload. Parallelizable means a genuine fan-out: two
    or more frontier stories that form an antichain (no member transitively
    depends on another, directly or through a story off the frontier) AND
    have disjoint file domains. A single-story frontier, overlapping domains,
    or a dependency edge within the frontier all mean solo — and when the
    frontier degrades to solo for the dependency reason, /xp-schedule's solo
    path promotes the lowest-id dep-satisfied story first, which is the
    dependency itself. ``overlap`` is ``file_domains_overlap_detail``'s dict
    forwarded verbatim — ``{"collisions": {path: [{"story_id", "origin",
    "pattern"?}, ...]}, "glob_forced": bool}`` — and stays exactly that; a
    ``pattern`` key appears only on a claim a GLOB entry produced; the dependency
    reason for a False verdict is deliberately NOT surfaced there. `collisions`
    and `glob_forced` are DISTINCT signals: a concrete path collision names
    the clashing stories, while glob_forced means a glob domain makes
    disjointness unprovable — a different message to the customer. Both are
    empty/false on a 0- or 1-story frontier, and all three top-level keys are
    always present, even when no sprint exists.
    """
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return {
            "frontier": [],
            "parallelizable": False,
            "overlap": {"collisions": {}, "glob_forced": False},
        }
    frontier = ready_frontier_data(sprint, treat_as_done=treat_as_done)
    overlap = file_domains_overlap_detail(sprint, frontier)
    parallelizable = (
        len(frontier) >= 2
        and not (overlap["glob_forced"] or overlap["collisions"])
        and not _frontier_has_internal_dependency(sprint, frontier)
    )
    return {"frontier": frontier, "parallelizable": parallelizable, "overlap": overlap}


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
    from sprint_store import load_sprint

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

    Backs the `next-in-progress` query — surfaces the next dep-satisfied
    in-progress story for /xp-schedule promotion/branching off the merged
    sprint tip, but only when its deps are actually satisfied. Cascade-defer
    naturally excludes blocked stories — a deferred story's status is
    "deferred", not "done", so any in-progress story depending on it fails
    the "all deps done" check and is skipped.

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

    Backs the `next-scheduled` query — surfaces the next dep-satisfied
    scheduled story so /xp-schedule can promote it to in-progress and
    branch it off the merged sprint tip. Same cascade-defer semantics
    as next_in_progress_story_id.
    """
    return _next_story_id_with_status(smm_dir, "scheduled", treat_as_done=treat_as_done)
