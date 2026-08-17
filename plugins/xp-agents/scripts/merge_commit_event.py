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
import commit_emit
import commit_handling
import commits
import identity
import review_records
import sprint_store
from event_schema import METADATA_KEY_COMMIT_HASH

# Sentinel for the optional ``sprint`` pre-read: ``None`` is a VALID passed
# value (an absent/corrupt sprint loads to None and fails open), so it can't
# double as "not provided". A unique object can. ``events`` needs no sentinel —
# a real pre-read is always a list, so ``None`` unambiguously means "read own".
_UNSET = object()


def append_merge_commit_event(
    cwd: str,
    smm_dir: Path | None,
    source: str,
    *,
    events: list[dict] | None = None,
    sprint: object = _UNSET,
) -> None:
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

    Optional ``events``/``sprint`` pre-reads let ``cmd_merge`` share ONE locked
    events read + ONE sprint load with ``trailer_gate.advisory`` (closes the
    recorded double-read debt). ``events is None`` → read own under flock; a
    passed list (possibly empty) is used as-is. ``sprint is _UNSET`` → load own
    + fail open; a passed value (including ``None``) is used as-is. BOTH readers
    of ``events`` here — the dedup scan and ``merge_resolves``' recorded-commit
    filter — need only PRIOR events, which a pre-append snapshot captures (taken
    after the merge landed), so sharing is safe.
    """
    if smm_dir is None:
        return
    commit_hash = commits.get_head_commit_hash(cwd)
    if not commit_hash:
        return
    # Read under shared flock for dedup and the range filter — we need the list
    # (commit-hash lookup is a linear scan), not the resolution graph. Using
    # load_events_with_resolutions here would pay an O(N) resolution.compute
    # pass on every close-cycle merge and throw the result away. A pre-read from
    # cmd_merge (a list) is used directly to avoid a second locked read.
    if events is None:
        events = _common.read_events_locked(smm_dir, "close-common-merge-dedup")
    if any(
        e.get("type") == _common.COMMIT
        and e.get("metadata", {}).get(METADATA_KEY_COMMIT_HASH) == commit_hash
        for e in events
    ):
        return
    files = commits.get_committed_files(cwd)
    raw_body = commits.get_commit_message_body(cwd) or f"Merge {source}"
    code_file_count = code_files.count_code_files(files)
    # `is_merge` derivation and content cleaning both mirror
    # `commit_emit.build_commit_event` — this emitter is the one caller that
    # used to invent a second answer for each. See that function for the full
    # rationale (fail-safe direction on an unknown parent count, `is None` vs
    # truthiness for a root commit). No `if commit_hash` guard as there: the
    # early return above already left it truthy.
    parent_count = commits.head_parent_count(cwd, commit_hash)
    is_merge = parent_count is not None and parent_count > 1
    authored, body, has_resolves_trailer = commit_emit.parse_commit_body(raw_body)
    resolves = authored
    # AUTHORED first, then the bounded merged-range derivation unioned onto it, via
    # the same helper both hook routes use. Never REPLACE with the derivation:
    # `raw_body` is read back from HEAD, so it is whatever actually landed and can
    # carry a trailer; and the range is bounded only by the source/target
    # relationship, so a story branch that back-merged `main` drags main's commits
    # in at close.
    #
    # `has_resolves_trailer` is AUTHORED-only: it RECORDS that somebody wrote a
    # trailer, and a re-parsed id is not one. Now that the tag is derived rather
    # than asserted, that costs a rate as well as the truth of the record — an
    # untagged event (unknown parent count, or a plain HEAD after an "Already up
    # to date" merge) is IN the trailer metrics. Which is why the derivation below
    # is gated on the tag: on an event that counts, a re-parsed id would score as
    # a link nobody authored.
    if is_merge:
        resolves = commit_emit.merge_resolves(cwd, commit_hash, resolves, events=events)
    # Degrade gracefully on a corrupt/schema-invalid sprint.json: the merge
    # itself already succeeded on target, and the surrounding push/delete/
    # remote-prune chain must continue. Matches close_verify_gate's
    # established fail-open posture for SMM-state errors here.
    if sprint is _UNSET:
        sprint = sprint_store.load_sprint_fail_open(smm_dir)
    # What the tag means, and what it excludes, is stated once in
    # `commit_emit.build_commit_event` — this emitter now derives it the same
    # way, so it has nothing of its own to add.
    # Tag merges whose source is a free branch —
    # honored by retro_metrics alongside is_merge. (A free→primary merge is
    # both: it carries is_merge from this code path AND should be flagged as
    # free for any future metric that wants to bucket free-mode close cycles
    # separately.)
    event = commit_handling.make_commit_event(
        identity.CLOSE_CYCLE_AGENT_ID,
        body,
        commit_hash=commit_hash,
        files=files,
        code_file_count=code_file_count,
        story_id=identity.extract_story_id(source),
        sprint_id=sprint["sprint_id"] if isinstance(sprint, dict) else None,
        resolves=resolves,
        has_resolves_trailer=has_resolves_trailer,
        is_merge=is_merge,
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
    # The merge always runs at orchestrator cwd, so the session and the repo
    # are the same directory here — named separately anyway, because which one
    # each record wants is the thing that drifted.
    watermark_key = identity.review_watermark_key(cwd)
    flags_key = identity.review_flags_key(cwd)
    # Same fail-open posture as the sprint_store load above: the merge already
    # succeeded on target and the surrounding push/delete/remote-prune chain
    # must continue. A symlinked / unwritable marker path is a SMM-state
    # problem, not a merge-correctness problem — surface it on stderr but
    # don't abort the chain (leaving the source merged-but-unpushed would
    # force the user into a manual cleanup that re-merge can't redo).
    try:
        review_records.end_review_cycle(smm_dir, watermark_key, flags_key, commit_hash)
    except (OSError, ValueError) as exc:
        sys.stderr.write(
            f"warn: failed to reset review cycle after merge ({exc}); "
            "next commit's review gate may need a manual reset\n"
        )
