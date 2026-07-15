#!/usr/bin/env python3
"""Force-drop recording for spawn_teammate's re-spawn cleanup.

A re-spawn that force-drops (`git branch -D`) a genuinely-unmerged branch leaves
it ABSENT with no merge — the sole crack in the mark-done gate's "branch absence
implies merged" keystone (story_done_gate). This module records that drop (R, a
`debt` event) so the gate can tell an abandoned branch apart from a merged-then-
deleted one, and supersedes it (S, a `status` event carrying metadata.resolves)
once the re-spawn re-creates the branch. Split out of spawn_teammate.py to keep
that file under the 500-line cap; imported back there for cleanup_existing /
create_worktree.
"""

import subprocess
from pathlib import Path

# `worktree` import bootstraps smm/ onto sys.path (mirrors spawn_teammate.py);
# pinned first via `isort: split` so the SMM-side imports below resolve.
import worktree  # isort: split

import _common
import event_schema
import identity

# The debt-event action discriminator is shared with the consumer
# (story_done_gate) via event_metadata so the two legs cannot drift into a
# gate-fails-open asymmetry. The supersede action has no reader (the gate clears
# via metadata.resolves), so it stays a local literal.
_FORCE_DROP_ACTION = event_schema.DEBT_ACTION_BRANCH_FORCE_DROPPED
_RESPAWN_ACTION = "branch_respawned"


def peek_dropped_ref(name: str, cwd: str) -> tuple[str, str]:
    """The (branch, tip sha) the worktree has checked out, read BEFORE removal.

    Must be peeked first: HEAD (and the sha it names) vanishes with the
    directory. Mirrors ``worktree.remove_worktree_dir``'s branch derivation --
    the HEAD-derived ref, falling back to the worktree ``name`` on a detached or
    unreadable HEAD -- so the recorded branch matches what ``remove_worktree``
    actually force-drops. ``sha`` is "" only when git cannot be read there.

    (Re-derived here because ``BranchRemoval`` does not carry the dropped
    (branch, sha); folding it into worktree.py is filed as debt.)
    """
    branch = name
    sha = ""
    try:
        wt = worktree.worktree_path(name, cwd)
    except RuntimeError:
        return branch, sha
    if not wt.is_dir():
        return branch, sha
    head = identity.get_current_branch(str(wt))
    if head and head != "HEAD":
        branch = head
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(wt),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        sha = result.stdout.strip()
    return branch, sha


def record_force_drop(
    smm_dir: str | Path, story_id: str | None, branch: str, sha: str
) -> str:
    """Append the force-drop record R (a ``debt`` event) and return its id.

    Built via the project's event API (make_event/append_safe), the same path
    every other script uses -- no hand-rolled JSONL.
    """
    event = _common.make_event(
        _common.DEBT,
        "spawn_teammate",
        f"Force-dropped unmerged branch {branch} (tip {sha or 'unknown'}) during "
        f"re-spawn cleanup: the branch's work never merged, so its absence is "
        f"abandonment, not a landed merge. The mark-done gate reads this to block "
        f"marking the story done unless the branch is re-created or the merge is "
        f"waived on the record.",
        files=[],
        metadata={
            "action": _FORCE_DROP_ACTION,
            "branch": branch,
            "dropped_sha": sha,
            "story_id": story_id or "",
        },
    )
    _common.append_safe(Path(smm_dir), event)
    return event["id"]


def record_respawn_supersede(
    smm_dir: str | Path, story_id: str | None, branch: str, drop_id: str
) -> None:
    """Append the supersede record S (a ``status`` carrying metadata.resolves) --
    resolution.compute_resolutions marks the drop R resolved once S lands."""
    event = _common.make_event(
        _common.STATUS,
        "spawn_teammate",
        f"Re-spawned worktree for {branch}; the earlier force-drop is superseded "
        f"-- the branch was re-created, so it no longer signals abandoned work.",
        working_on=[],
        metadata={
            "action": _RESPAWN_ACTION,
            "resolves": [drop_id],
            "branch": branch,
            "story_id": story_id or "",
        },
    )
    _common.append_safe(Path(smm_dir), event)
