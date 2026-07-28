#!/usr/bin/env python3
"""The body-to-event emission sequence shared by every commit-event path.

`_handle_commit`'s success path built its commit event inline. A second path
— the HEAD-moved rebuild, which recovers the event for a commit whose command
string the parser could not read — needs the SAME sequence: trailer
extraction, the Co-Authored-By strip, the unlinkable-trailer advisory, sprint
load, story attribution, free-branch tagging and cadence stamping. Copying it
is how the third emitter (`merge_commit_event.append_merge_commit_event`)
already drifted three ways, so it lives here once.

Placement: deliberately NOT `commit_event.py` (404 lines — this sequence plus
its signature would push it past the 450 sub-cap) and NOT `commit_handling.py`
(392 lines, which would land near 470 once the rebuild sits beside it). A third
module keeps every file under the cap and gives the sequence a name.

Scope is event CONSTRUCTION only. The success path's other post-commit effects
— commit-size concern, lint resolution, security-marker consume, review-cycle
reset, QR nudge — stay with their caller, which is the shape
`_handle_commit`'s `is_xp_agent_leak` mode already documents.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import commit_event
import commits
import identity
import resolution

__all__ = ["build_commit_event"]

_COAUTHOR_TRAILER_RE = re.compile(r"\n+\s*Co-Authored-By:.*$", re.DOTALL)


def build_commit_event(
    smm_dir: Path,
    agent_id: str,
    cwd: str,
    raw_body: str | None,
    commit_hash: str | None,
    *,
    events: list[dict],
    committed_files: list[str],
    code_file_count: int,
    review_cadence: str,
) -> dict | None:
    """Turn a commit body into a type=commit event. None when there is no body.

    `events` is the caller's already-locked read of the event log — used to
    index resolvable ids for the unlinkable-trailer advisory, so this helper
    never takes a second lock on the PostToolUse hot path. `review_cadence` is
    likewise passed in rather than re-read: both callers need it for their own
    reasons, and reading it here too would double the marker read.

    Side effect: appends the unlinkable-trailer concern when the trailer names
    an id the resolver cannot see. That advisory belongs to the body, not to
    the caller, which is why it moved in here with the rest of the sequence.
    """
    if not raw_body:
        return None
    resolves, body, has_trailer = commits.extract_resolves_trailer(raw_body)
    body = _COAUTHOR_TRAILER_RE.sub("", body).strip()

    # A trailer naming an id absent from the live log resolves nothing.
    # `resolve_prefix` is a lookup over the events it is handed, so an archived
    # or mistyped target no-ops in silence. Record the commit either way — a
    # dangling id is harmless — but surface the ids that will not link.
    #
    # `known` must be the SAME index the resolver consults: top-level event ids
    # PLUS nested retrospective try-item ids (a trailer can close a retro Try).
    # Membership is an exact-id test: `extract_resolves_trailer` already
    # validated every id to exactly 12 hex (EVENT_ID_RE), and event ids are
    # exactly 12 hex too, so no id is ever a strict prefix of another — the
    # prefix-scan branch resolve_prefix keeps for short ids is unreachable here.
    if resolves:
        known = resolution.resolvable_event_ids(events)
        unknown = [rid for rid in resolves if rid not in known]
        if unknown:
            commit_event._record_unlinkable_trailer(smm_dir, agent_id, unknown)

    import branching
    import sprint_store

    sprint = sprint_store.load_sprint(smm_dir)

    story_id = commit_event._resolve_story_id(
        smm_dir, cwd, committed_files, sprint=sprint, message=body
    )

    # Tag commits emitted on a free branch — honored by
    # retro_metrics._compute_resolves_link_rate as a conditional-include
    # filter (counts only when the commit carries a Resolves trailer).
    # get_current_branch returns "" on git failure; is_free_branch("") is
    # False (safe-fail: untagged commit drops into the denominator).
    is_free_session = branching.is_free_branch(identity.get_current_branch(cwd))

    return commit_event.make_commit_event(
        agent_id,
        body,
        commit_hash=commit_hash,
        files=committed_files,
        code_file_count=code_file_count,
        story_id=story_id,
        sprint_id=sprint["sprint_id"] if sprint is not None else None,
        resolves=resolves,
        has_resolves_trailer=has_trailer,
        is_free_session=is_free_session,
        review_cadence=review_cadence,
    )
