#!/usr/bin/env python3
"""Emit a type=commit event for a close-cycle merge HEAD.

Extracted from close_common.py. See ``append_merge_commit_event`` for the
merge-gap rationale and metadata shape. Stdlib-only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import branching
import code_files
import commit_handling
import commits
import identity
import markers
import sprint_store
from event_schema import METADATA_KEY_COMMIT_HASH


def append_merge_commit_event(cwd: str, smm_dir: Path | None, source: str) -> None:
    """Append a type=commit event for the merge HEAD just produced by
    ``branching.merge_branch``.

    Closes the merge-gap commit-event hole: the parent Bash PreToolUse hook
    only matches top-level ``git commit`` shells, so the inner
    ``git merge --no-ff`` subprocess spawned by ``branching.merge_branch``
    leaves no event. We emit one here mirroring
    ``commit_handling._handle_commit``'s metadata shape (action, code_commit,
    code_file_count, commit_hash, story_id, sprint_id) so downstream
    accounting (commit counts, story attribution, resolves-link rate) sees
    close-cycle merges.

    No-op when ``smm_dir`` is None — defends programmatic callers
    (in-process tests, future scripts) that invoke ``cmd_merge`` without
    threading ``--smm-dir``. All four shipped close skills now pass it.
    Dedupes by ``commit_hash`` so a retried/"Already up to date" re-merge
    cannot double-emit.
    """
    if smm_dir is None:
        return
    commit_hash = commits.get_head_commit_hash(cwd)
    if not commit_hash:
        return
    # Read events under shared flock for dedup — we only need the events list
    # (commit-hash lookup is a linear scan), not the resolution graph. Using
    # load_events_with_resolutions here would pay an O(N) resolution.compute
    # pass on every close-cycle merge and throw the result away.
    events = _common.read_events_locked(smm_dir, "close-common-merge-dedup")
    if any(
        e.get("type") == _common.COMMIT
        and e.get("metadata", {}).get(METADATA_KEY_COMMIT_HASH) == commit_hash
        for e in events
    ):
        return
    files = commits.get_committed_files(cwd)
    body = commits.get_commit_message_body(cwd) or f"Merge {source}"
    code_file_count = code_files.count_code_files(files)
    # Degrade gracefully on a corrupt/schema-invalid sprint.json: the merge
    # itself already succeeded on target, and the surrounding push/delete/
    # remote-prune chain must continue. Matches close_verify_gate's
    # established fail-open posture for SMM-state errors here.
    try:
        sprint = sprint_store.load_sprint(smm_dir)
    except (sprint_store.SprintCorruptError, OSError):
        sprint = None
    # is_merge=True excludes this event from resolves_link_rate accounting:
    # the merge HEAD aggregates already-recorded story commits, each of
    # which carries its own Resolves trailer. Counting the merge commit
    # in the denominator would dilute the rate without a meaningful
    # numerator (merge commit messages don't carry Resolves trailers).
    # Tag merges whose source is a free branch — honored by retro_metrics
    # alongside is_merge. (A free→primary merge is both: it carries is_merge
    # from this code path AND should be flagged as free for any future metric
    # that wants to bucket free-mode close cycles separately.)
    event = commit_handling.make_commit_event(
        "close_common",
        body,
        commit_hash=commit_hash,
        files=files,
        code_file_count=code_file_count,
        story_id=identity.extract_story_id(source),
        sprint_id=sprint["sprint_id"] if sprint is not None else None,
        is_merge=True,
        is_free_session=branching.is_free_branch(source),
    )
    _common.bulk_append_safe(smm_dir, [event])

    # Reset the orchestrator's review cycle to the merge HEAD. The Bash
    # PreToolUse hook only matches top-level `git commit` shells, so the
    # `commit_handling._handle_commit` reset that fires for normal commits
    # is bypassed for merges driven by `branching.merge_branch` here. Left
    # alone, the prior commit's `quality_review_done=True` marker would
    # latch the review gate against the next solo commit on the sprint
    # branch.
    agent_id = identity.resolve_agent_id_from_cwd(cwd)
    # Same fail-open posture as the sprint_store load above: the merge already
    # succeeded on target and the surrounding push/delete/remote-prune chain
    # must continue. A symlinked / unwritable marker path is a SMM-state
    # problem, not a merge-correctness problem — surface it on stderr but
    # don't abort the chain (leaving the source merged-but-unpushed would
    # force the user into a manual cleanup that re-merge can't redo).
    try:
        markers.reset_review_cycle(smm_dir, agent_id, commit_hash)
    except (OSError, ValueError) as exc:
        sys.stderr.write(
            f"warn: failed to reset review cycle after merge ({exc}); "
            "next commit's review gate may need a manual reset\n"
        )
