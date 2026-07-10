#!/usr/bin/env python3
"""Status-check helpers for sprint.json.

Extracted from sprint_store.py once that module crossed 500 lines.
sprint_store re-exports every name defined here so existing call sites
(`from sprint_store import has_active_stories`) keep working.

`load_sprint` is imported lazily inside each function so this module can
import cleanly without a cycle when sprint_store re-exports back.
"""

from pathlib import Path

import file_domain_lock
from sprint_schema import (
    ACTIVE_STORY_STATUSES,
    IN_MOTION_STORY_STATUSES,
    UNDER_ACCEPTANCE_STORY_STATUSES,
)
from triage import extract_file_domain_paths


def has_active_stories(smm_dir: Path) -> bool:
    """True if sprint has ready or in-progress stories."""
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return has_active_stories_data(sprint)


def has_active_stories_data(data: dict) -> bool:
    """True if sprint dict has ready or in-progress stories."""
    return any(s["status"] in ACTIVE_STORY_STATUSES for s in data["stories"])


def has_stories_with_status(smm_dir: Path, status: str) -> bool:
    """True if sprint has any story matching `status`."""
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return has_stories_with_status_data(sprint, status)


def has_stories_with_status_data(data: dict, status: str) -> bool:
    """True if sprint dict has any story matching `status`.

    Sibling to has_stories_with_status for callers that already hold
    the loaded sprint dict.
    """
    return any(s["status"] == status for s in data["stories"])


def has_in_progress_stories(smm_dir: Path) -> bool:
    """True if sprint has in-progress stories."""
    return has_stories_with_status(smm_dir, "in-progress")


def has_in_progress_stories_data(data: dict) -> bool:
    """True if sprint dict has in-progress stories."""
    return has_stories_with_status_data(data, "in-progress")


def has_reviewing_stories(smm_dir: Path) -> bool:
    """True if sprint has reviewing stories."""
    return has_stories_with_status(smm_dir, "reviewing")


def has_reviewing_stories_data(data: dict) -> bool:
    """True if sprint dict has reviewing stories."""
    return has_stories_with_status_data(data, "reviewing")


def has_closing_stories(smm_dir: Path) -> bool:
    """True if sprint has closing stories."""
    return has_stories_with_status(smm_dir, "closing")


def has_closing_stories_data(data: dict) -> bool:
    """True if sprint dict has closing stories."""
    return has_stories_with_status_data(data, "closing")


def select_closing_stories(stories: list[dict]) -> list[dict]:
    """Return stories in the /xp-story-close pipeline."""
    return [s for s in stories if s.get("status") == "closing"]


def has_in_motion_stories(smm_dir: Path) -> bool:
    """True if sprint has in-motion (in-progress, reviewing, or closing) stories."""
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return has_in_motion_stories_data(sprint)


def has_in_motion_stories_data(data: dict) -> bool:
    """True if sprint dict has in-motion stories (in-progress, reviewing, closing)."""
    return any(s["status"] in IN_MOTION_STORY_STATUSES for s in data["stories"])


def has_under_acceptance_stories(smm_dir: Path) -> bool:
    """True if sprint has reviewing or closing stories.

    Stories inside the per-story accept dispatch window. See
    sprint_schema.UNDER_ACCEPTANCE_STORY_STATUSES.
    """
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return has_under_acceptance_stories_data(sprint)


def has_under_acceptance_stories_data(data: dict) -> bool:
    """True if sprint dict has reviewing or closing stories."""
    return any(s["status"] in UNDER_ACCEPTANCE_STORY_STATUSES for s in data["stories"])


def select_in_motion_stories(stories: list[dict]) -> list[dict]:
    """Return in-motion stories (in-progress, reviewing, or closing)."""
    return [s for s in stories if s.get("status") in IN_MOTION_STORY_STATUSES]


def has_ready_stories(smm_dir: Path) -> bool:
    """True if sprint has ready stories."""
    return has_stories_with_status(smm_dir, "ready")


def has_scheduled_stories(smm_dir: Path) -> bool:
    """True if sprint has scheduled stories (queued for this iteration)."""
    return has_stories_with_status(smm_dir, "scheduled")


def schedule_gate_active(smm_dir: Path) -> bool:
    """True in the pre-promotion window: scheduled stories exist AND no story
    is in motion (in-progress, reviewing, or closing).

    The trigger the /xp-schedule write + EnterPlanMode gates fire on. It is
    state-derived (no marker to rm past): the only legitimate exit is
    /xp-schedule promoting a frontier scheduled->in-progress, which puts a
    story in motion and self-clears the gate. False when no sprint.

    The in-motion guard (not just no-in-progress) keeps the gate quiet through
    the /xp-accept review + /xp-story-close window: a story reviewing/closing
    with the next frontier still scheduled is NOT the pre-promotion window, so
    review-cycle fixes to the in-motion story must not be blocked by a demand
    to promote the next frontier mid-close. Once the close lands (story->done)
    nothing is in motion and the gate re-fires to force scheduling the next.
    """
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return schedule_gate_active_data(sprint)


def schedule_gate_active_data(data: dict) -> bool:
    """True if the sprint dict has scheduled stories and no story in motion.

    Sibling to schedule_gate_active for callers holding the loaded dict.
    """
    return has_stories_with_status_data(
        data, "scheduled"
    ) and not has_in_motion_stories_data(data)


def in_progress_is_teammate(smm_dir: Path) -> bool:
    """True iff any in-progress story has execution_mode == 'teammate'.

    The signal subagent_stop's plan-review gate keys on: at plan-review-done
    time the just-planned story is in-progress, and /xp-schedule promotes a
    homogeneous batch. Only teammate-mode plans need /xp-assign, so a solo or
    unset in-progress story leaves no .assign-pending marker. Conservative
    default False (no sprint / no in-progress / solo / unset).
    """
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return in_progress_is_teammate_data(sprint)


def in_progress_is_teammate_data(data: dict) -> bool:
    """True iff the sprint dict has an in-progress story with
    execution_mode == 'teammate'. Sibling to in_progress_is_teammate for
    callers holding the loaded dict.
    """
    return any(
        s.get("status") == "in-progress" and s.get("execution_mode") == "teammate"
        for s in data.get("stories", [])
    )


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
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    scheduled = [s["id"] for s in sprint["stories"] if s.get("status") == "scheduled"]
    return file_domains_overlap_data(sprint, scheduled)


def file_domains_overlap_detail(data: dict, story_ids: list[str]) -> dict:
    """Why the named stories can or cannot run in parallel, with the facts.

        {"collisions": {path: [{"story_id", "origin"}, ...]}, "glob_forced": bool}

    `collisions` is `file_domain_lock.collision_report`'s output forwarded
    unchanged — already sorted by path, already dependency- and terminal-aware,
    already tagging each claim `authored` vs `auto_included`. Reshaping it here
    would create a second place to drift from the one file_domain parser.

    `glob_forced` is a SEPARATE signal, never folded into `collisions`.
    `collision_report` compares glob tokens as literal strings, so a
    glob-declared domain reads as disjoint there. `extract_file_domain_paths`
    is reused as the glob DETECTOR (it raises ValueError on a glob with no
    candidates/cwd) — the exact oracle the overlap bool has always relied on,
    so conservatism fires on exactly the old inputs. Callers need the two apart
    to say "both stories claim x.py" versus "a glob domain means disjointness
    can't be proven".

    Fewer than two named stories: no pair, so no claim about paths, and the
    detector never runs.
    """
    wanted = set(story_ids)
    subset = [s for s in data["stories"] if s.get("id") in wanted]
    if len(subset) < 2:
        return {"collisions": {}, "glob_forced": False}

    # Scoping to `subset` is safe: a frontier member can never depend on
    # another frontier member (deps must be `done` to be satisfied), so the
    # dependency-awareness collision_report applies is a no-op within one.
    collisions = file_domain_lock.collision_report({"stories": subset})

    glob_forced = False
    for story in subset:
        # Filter non-str BEFORE the detector: entry_to_paths indexes the entry
        # and raises TypeError, not ValueError, on anything else.
        entries = [e for e in (story.get("file_domain") or []) if isinstance(e, str)]
        try:
            extract_file_domain_paths(entries)
        except ValueError:
            glob_forced = True
            break

    return {"collisions": collisions, "glob_forced": glob_forced}


def file_domains_overlap_data(data: dict, story_ids: list[str]) -> bool:
    """True when 2+ of the named stories share a file in their file_domain.

    Pure helper over a loaded sprint dict. Powers both the /xp-assign
    auto-pick-solo check (over all scheduled stories) and the /xp-schedule
    ready-frontier parallelizable verdict (over just the frontier subset).
    Returns False for fewer than two named stories (no pair to overlap).

    Re-derived from `file_domains_overlap_detail` so the two answers can never
    disagree. Conservative: True when a story declares a glob, so callers pick
    solo rather than degrade to "no overlap → safe to parallelize".

    Being a view of the detail helper makes this dependency- and
    terminal-aware: stories serialized by a dependency edge may share files
    without overlapping, since they can never be worked at the same time.
    """
    detail = file_domains_overlap_detail(data, story_ids)
    return detail["glob_forced"] or bool(detail["collisions"])


def is_complete(smm_dir: Path) -> bool:
    """True when no ready or in-progress stories remain."""
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return True
    if not sprint["stories"]:
        return True
    return not has_active_stories_data(sprint)
