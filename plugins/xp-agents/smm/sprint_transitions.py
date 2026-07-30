#!/usr/bin/env python3
"""Story status transitions for sprint.json — the locked write path.

Extracted from sprint_store.py once that module crossed 500 lines.
sprint_store re-exports every public name defined here so existing call sites
(`from sprint_store import update_story_status`) keep working.

One responsibility: move a story from one status to another, under one lock,
through one helper. The two public writers differ only in whether they check an
expected prior status; everything else — validation, the lock, the start-time
collision check, the write — is shared, because a gate installed in one of two
documented entrances is fail-open.

`load_sprint` and friends are imported lazily inside each function so this
module can import cleanly without a cycle when sprint_store re-exports back.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import file_domain_lock
from _append_impl import flock_with_timeout
from sprint_schema import IN_MOTION_STORY_STATUSES, VALID_STORY_STATUSES

_SPRINT_LOCK_NAME = "sprint.lock"


@contextmanager
def _sprint_lock(smm_dir: Path) -> Iterator[None]:
    """Hold an exclusive flock on sprint.lock for the duration of the block.

    Held by `_write_story_status`, which is BOTH status writers, so the
    load-check-write is one indivisible critical section — a second writer
    racing this one will see the post-update state when its load runs, not the
    pre-update snapshot. The shared `flock_with_timeout` helper provides the
    SIGALRM-bounded acquire and suppress-OSError-on-release semantics
    so a deadlocked sibling can't wedge the wrapper.

    `update_story_status` was originally outside this lock, when the CAS was
    the only caller that needed atomicity. The start-time collision check made
    that untenable: an unlocked read-check-write lets two simultaneous
    promotions each read a clean baseline and both write, which is the exact
    race the check exists to stop. Other mutators (set_branch, set_story_branch,
    edit_story) still do NOT take this lock — they write fields no gate reads
    across processes.
    """
    with flock_with_timeout(smm_dir / _SPRINT_LOCK_NAME):
        yield


def _refuse_start_on_live_collision(smm_dir: Path, sprint: dict) -> None:
    """Raise if starting a story would put two RUNNING stories on one path.

    The second necessary line, not belt-and-braces. /xp-schedule's frontier
    check refuses to parallelize an overlapping frontier, but it scopes to
    frontier members — all queued, never started — so it structurally cannot
    see a story that is already running. And a claim that only holds while its
    story runs leaves a staggered hole the frontier check cannot close: two
    queued stories on one path coexist legally, the frontier promotes them one
    at a time, and one story alone is never a pair. So the same question is
    asked again at START time, when both stories are finally live.

    Reuses `sprint_save.introduced_collisions` rather than inventing a second
    attribution. Its "colliding set GREW versus the on-disk baseline" rule
    already covers a status change: its docstring names a dependency edit that
    makes two shared-path stories concurrent as the same shape, since
    concurrency is not a domain diff.

    Called with the POST-transition sprint, in-memory and unsaved, so a refusal
    leaves the file untouched.
    """
    import sprint_save  # function-local: sprint_save imports sprint_store (cycle)

    introduced = sprint_save.introduced_collisions(sprint, smm_dir, running_only=True)
    if introduced:
        raise ValueError(file_domain_lock.format_collision_report(introduced))


def _write_story_status(
    smm_dir: Path, story_id: str, status: str, *, expected: str | None = None
) -> bool:
    """The single locked read-check-write behind both status writers.

    `expected` None is the unconditional write; a string makes it a
    compare-and-swap that returns False (file untouched) on a mismatch. The
    start-time collision check runs INSIDE the lock — around it would restore
    the TOCTOU it exists to close.

    The check is narrow on purpose: only a transition that puts a story in
    motion from a status that was NOT already in motion. Already-running to
    already-running (`in-progress` -> `reviewing` -> `closing`) skips it,
    because re-checking there would pay a filesystem sister-expansion for an
    answer that cannot have changed and would compare a story against its own
    claim. It is keyed on the in-motion SET, not on `in-progress` alone: the
    new status is arbitrary at both entrances, and every in-motion status
    makes the claim live, so a parked story jumped straight to `reviewing`
    would otherwise go live past the gate.
    """
    if status not in VALID_STORY_STATUSES:
        valid = sorted(VALID_STORY_STATUSES)
        raise ValueError(f"Invalid status {status!r}, must be one of {valid}")

    from sprint_store import _load_story, save_sprint

    with _sprint_lock(smm_dir):
        sprint, story = _load_story(smm_dir, story_id)
        if expected is not None and story["status"] != expected:
            return False
        was_running = story["status"] in IN_MOTION_STORY_STATUSES
        story["status"] = status
        if status in IN_MOTION_STORY_STATUSES and not was_running:
            _refuse_start_on_live_collision(smm_dir, sprint)
        save_sprint(smm_dir, sprint, enforce_budget=False)
        return True


def update_story_status(smm_dir: Path, story_id: str, status: str) -> None:
    """Update a story's status in the sprint.

    Raises ValueError for an unknown status, a missing story/sprint, or a
    promotion to `in-progress` that would collide with a running story's
    file_domain (see `_refuse_start_on_live_collision`).
    """
    _write_story_status(smm_dir, story_id, status)


def update_story_status_if(
    smm_dir: Path, story_id: str, *, expected: str, new: str
) -> bool:
    """Atomic compare-and-swap on story status.

    Returns True when the on-disk status matched ``expected`` and the
    write to ``new`` succeeded; False when the status differed (no-op,
    file untouched). Raises ValueError for an unknown ``new`` status,
    a missing story id, a missing sprint, or a refused promotion.

    Closes the get_story → update_story_status TOCTOU window in
    spawn_teammate.py: the load-check-write runs under one flock so
    a story already advanced past ``expected`` (e.g. an orchestrator
    flipped it to ``done``) cannot be silently demoted.

    `--new` is arbitrary, so this is a second full entrance to `in-progress`
    and carries the same start-time gate as `update_story_status`. A gate on
    one of two documented entrances is fail-open.
    """
    return _write_story_status(smm_dir, story_id, new, expected=expected)
