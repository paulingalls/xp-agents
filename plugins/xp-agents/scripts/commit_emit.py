#!/usr/bin/env python3
"""Building commit events: the shared emission sequence, and the HEAD rebuild.

`_handle_commit`'s success path built its commit event inline. A second path —
`rebuild_at_head`, which recovers the event for a commit whose command string
the parser could not read — needs the SAME sequence: trailer extraction, the
Co-Authored-By strip, the unlinkable-trailer advisory, sprint load, story
attribution, free-branch tagging and cadence stamping. Copying it is how the
third emitter (`merge_commit_event.append_merge_commit_event`) already drifted
three ways, so it lives here once and both callers use it.

Placement: deliberately NOT `commit_event.py` and NOT `commit_handling.py`.
This module's own size would push either host past the 450-line sub-cap that
`tests/hooks/test_commit_event_rebuild.py` pins, so a third module keeps every
file under it and gives the sequence a name. Deliberately no line counts here:
the first draft quoted three, and the close-cycle fixes falsified all three
within the same sprint. `wc -l` is the source of truth; a docstring that
restates it is a second one that silently goes stale.

`build_commit_event`'s scope is event CONSTRUCTION only. The success path's
other post-commit effects — commit-size concern, lint resolution,
security-marker consume, QR nudge — stay with their caller, which is the shape
`_handle_commit`'s `is_xp_agent_leak` mode already documents. `rebuild_at_head`
takes the same narrow scope plus the review-cycle reset; see the comment at
that call for why it is the one effect the rebuild owns.
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import code_files
import commit_event
import commit_message
import commits
import identity
import markers
import resolution
import review_records

__all__ = [
    "HEAD_REBUILD_MAX_AGE_SECONDS",
    "build_commit_event",
    "parse_commit_body",
    "rebuild_at_head",
]

_COAUTHOR_TRAILER_RE = re.compile(r"\n+\s*Co-Authored-By:.*$", re.DOTALL)

# How young HEAD must be for the just-finished command to plausibly be what
# produced it. Ten minutes, not ten seconds: this hook fires after the WHOLE
# Bash call returns, and a pre-commit chain that runs a full test suite keeps
# the shell busy for minutes after git wrote the commit — the very condition
# (truncated stdout) that sends us down this path in the first place. Not
# hours either: every second of slack is a second in which a REJECTED commit
# atop somebody else's recent history starts to look like a success.
HEAD_REBUILD_MAX_AGE_SECONDS = 600

# An unexpanded shell expansion left in the message the hook recovered:
# `$VAR`, `${VAR}`, `$(...)`, or a backtick substitution. Only meaningful on a
# message form the shell EXPANDS — see `_message_unreadable_from_command`.
_UNEXPANDED_RE = re.compile(r"\$[({\w]|`")

# Reflog actions that mean "this HEAD was produced by committing". `%gs` spells
# an ordinary commit `commit` and a repo's first one `commit (initial)`, while
# an amend is `commit (amend)` — a DIFFERENT commit object whose predecessor
# may already carry an event — and `rebase`/`merge`/`reset`/`cherry-pick` are
# not this command's work at all.
_COMMIT_REFLOG_ACTIONS = frozenset({"commit", "commit (initial)"})


def parse_commit_body(raw_body: str | None) -> tuple[list[str], str, bool]:
    """`(resolves ids, the body an event's content is BUILT from, has_trailer)`.

    The derivation the event carries: `Resolves-Event:` trailers removed (their
    ids returned instead) and the Co-Authored-By block stripped.

    Public because a caller that needs this string must NOT read it back off
    the built event: `_common.make_event` runs `extract_refs_suffix` on
    `content`, which removes a trailing `[refs: <id>]` span and routes its ids,
    so `event["content"]` is a DERIVED value and not this one. One home for the
    rule keeps the two in step.
    """
    if not raw_body:
        return [], "", False
    resolves, body, has_trailer = commits.extract_resolves_trailer(raw_body)
    return resolves, _COAUTHOR_TRAILER_RE.sub("", body).strip(), has_trailer


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
    resolves, body, has_trailer = parse_commit_body(raw_body)

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


def _message_unreadable_from_command(command: str) -> bool:
    """Did the command withhold its message from the hook?

    The sharpest of the rebuild's guards, and the one that matches the defect
    it exists for: "an `-m`/`-F` argument the hook cannot expand". Two shapes
    qualify — no recoverable message at all (`-F <path>` the shell already
    deleted, `-F -` fed from a heredoc), and a message still carrying a live
    `$VAR` / `$(...)` / backtick that only the shell could have resolved.

    A message the hook CAN read, which simply did not match HEAD, is the
    opposite: positive evidence this command did not produce HEAD. That is a
    commit rejected on top of recent history, or one whose subject a
    commit-msg hook rewrote. Both must stay with the trace — recording there
    would fabricate a commit this command never made and honor a trailer off
    somebody else's message, resolving events on false evidence. That is a
    worse fail-open than the dropped trailer being fixed. It holds only for a
    command that RAN, so `rebuild_at_head` skips this when backgrounded.

    So the scan applies ONLY to a form the shell expands. A `$` or a backtick
    inside a single-quoted `-m`, a `<<'EOF'` heredoc, or a `-F <path>` body is
    a literal character git stored verbatim — reading it as an unresolved
    expansion armed the rebuild for ordinary subjects (this repo's own
    routinely contain backticks) and fabricated exactly the event the
    paragraph above refuses.
    """
    message, expands = commit_message.recover_commit_message(command)
    if not message:
        return True
    return expands and bool(_UNEXPANDED_RE.search(message))


def _head_is_a_freshly_landed_commit(cwd: str, commit_hash: str) -> bool:
    """Is HEAD a plain commit that landed a moment ago?

    Deliberately NOT "did this command make it" — that is what the hook
    cannot prove on this branch. Three signals, all required, because the
    branch is ambiguous without any one of them (a fourth,
    `_message_unreadable_from_command`, guards the caller side):

    * **Fresh.** An old HEAD means the command failed on top of history
      someone else wrote.
    * **One parent.** A manual `git merge` emits no event of its own, so a
      young merge HEAD is also unrecorded — and it is NOT a plain commit.
      Recording it as one would take the whole merged branch as `files`,
      with no `is_merge` tag and no authored trailer, straight into the
      resolves-link-rate denominator this story exists to improve.
    * **Reflog says `commit`.** Freshness and parent count both pass for a
      `rebase (pick)`, a `commit --amend` and a `reset` onto a young commit,
      none of which this command produced. Only the reflog separates them, so
      its ABSENCE vetoes rather than letting the first two signals stand alone
      — see the fail-closed reasoning at the return below. An earlier draft did
      degrade to allow there, and that was the widest remaining fabrication
      path.
    """
    facts = commits.head_landing_facts(cwd, commit_hash)
    if facts is None:
        return False
    committer_ts, parent_count, reflog_action = facts
    # Bounded at BOTH ends. `now - ts > MAX` alone reads a FUTURE committer date
    # as maximally fresh, so clock skew on the committing host would defeat this
    # guard outright rather than trip it. The housekeeping gate bounds the same
    # helper the same way (`0 <= age`); no grace window here, because unlike a
    # heartbeat a false refusal costs only the trace we recorded before.
    age = time.time() - committer_ts
    if not 0 <= age <= HEAD_REBUILD_MAX_AGE_SECONDS:
        return False
    if parent_count > 1:
        return False
    # Absence VETOES rather than degrading to allow. Degrading left the widest
    # residual fabrication path: with `core.logAllRefUpdates` off, an amend or a
    # reset/ff-merge onto a fresh unrecorded commit, then a failed unreadable
    # commit, satisfies every other guard and records an event for a commit this
    # command did not make — whose trailer then resolves real ids on false
    # evidence. Vetoing costs those repos only the trace they already got before
    # this story, so it is not a regression there; the asymmetry is lopsided.
    # Matches the recorded fail-closed doctrine for an unresolvable `git -C`.
    return reflog_action in _COMMIT_REFLOG_ACTIONS


def rebuild_at_head(
    smm_dir: Path,
    agent_id: str,
    cwd: str,
    command: str,
    commit_hash: str,
    *,
    events: list[dict],
    session_cwd: str,
    is_xp_agent_leak: bool = False,
    backgrounded: bool = False,
) -> bool:
    """Record the commit event for an unrecorded HEAD. True if one landed.

    `cwd` is the repo HEAD was probed in; `session_cwd` is the caller's own
    checkout. They differ under `git -C`, and the two review records below
    want different ones — see `identity.review_watermark_key`.

    Reached when both commit-success signals went blind — stdout truncated
    past git's `[branch hash] msg` line, and an `-m`/`-F` argument the hook
    cannot expand. The event then never gets built, and since a
    `Resolves-Event:` trailer is honored ONLY through `metadata.resolves`,
    every id the author named stays silently open. `backgrounded` — the tool
    call returned at LAUNCH — is the larger way both go blind at once.

    What this event claims is narrower than the success path's: "a commit
    exists at this hash with no event, and here is its message read back from
    git". NOT "this command produced it" — attribution to a particular command
    is precisely what the hook cannot prove here.

    False means "not claimed", and the caller must fall back to the trace so
    the observation is still recorded — an unreadable body must never become
    a silent return. Callers gate on commit-hash dedup only: a hash that
    already carries a TRACE (an earlier attempt whose body read failed) must
    remain rebuildable, or its trailer is dropped forever.
    """
    if not backgrounded and not _message_unreadable_from_command(command):
        return False
    if not _head_is_a_freshly_landed_commit(cwd, commit_hash):
        return False
    raw_body = commits.get_commit_message_body(cwd)
    if not raw_body:
        return False
    committed_files = commits.get_committed_files(cwd)
    event = build_commit_event(
        smm_dir,
        agent_id,
        cwd,
        raw_body,
        commit_hash,
        events=events,
        committed_files=committed_files,
        code_file_count=code_files.count_code_files(committed_files),
        review_cadence=markers.read_review_cadence(smm_dir),
    )
    if event is None:
        return False
    _common.bulk_append_safe(smm_dir, [event])

    # Reset the review cycle, as the success path does for a commit it could
    # confirm. Omitting it is the documented hazard the merge emitter had to
    # fix: a commit event recorded without a reset leaves the PRIOR cycle's
    # quality-review flag latched, so the next commit's gate reads satisfied
    # off a review that predates this commit — a fail-open on the gate. The
    # evidence that justified recording the event justifies this too; where it
    # is wrong, the cost is one extra review, which is the safe direction.
    #
    # Skipped on a leaked xp- agent_type for the same reason the success path
    # skips it: recording the commit is always right, but mutating cycle state
    # under a wrong identity is not.
    if not is_xp_agent_leak:
        review_records.write_review_watermark(
            smm_dir, identity.review_watermark_key(cwd), commit_hash
        )
        review_records.clear_review_flags(
            smm_dir, identity.review_flags_key(session_cwd)
        )
    return True
