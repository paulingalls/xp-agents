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
    "merge_resolves",
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
# may already carry an event — and `rebase`/`reset`/`cherry-pick` reach a HEAD
# by means this path cannot describe. `merge` has its own arm below.
_COMMIT_REFLOG_ACTIONS = frozenset({"commit", "commit (initial)"})

# Matched as a LEADING WORD, never by equality: `%gs` spells it `merge side: …`,
# so an equality test matches nothing and — this path failing closed — records
# nothing while looking correct. `commit (merge)` — a conflict finished by hand —
# is the same landing, matched EXACTLY (`commit (amend)` on a merge is another
# object). Both pinned in `test_manual_merge_commit_event.py`.
_MERGE_REFLOG_ACTION = "merge"
_CONFLICT_FINISH_REFLOG_ACTION = "commit (merge)"

# The leading word alone is NOT sufficient, and assuming it was shipped a
# fabrication: a fast-forward creates no commit yet spells itself `merge X:
# fast-forward`, and lands on a merge often enough that the parent arm routes it
# here. So the DETAIL decides, as an ALLOWLIST — anything but git announcing a
# created merge falls to the trace, as before the merge arm, so it costs nothing
# new. A denylist would enumerate every other non-creating spelling forever,
# failing OPEN on a miss; `test_commit_event_provenance.py` holds what it took.
_MERGE_CREATED_DETAIL_PREFIX = "merge made by"


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


def merge_resolves(
    cwd: str,
    commit_hash: str,
    authored: list[str],
    *,
    events: list[dict],
) -> list[str]:
    """`authored` UNION the trailers of merged-in commits whose event never landed.

    ALL THREE merge emitters route through here, which is the point — it was
    written twice with different answers, and the close-cycle copy replaced where
    the hook routes unioned.

    ONLY commits whose own event never landed. That is the entire rationale for
    re-parsing at all — a teammate's per-commit events can fail to reach the shared
    log, leaving the merge HEAD the only surviving record of that work — and
    unfiltered the derivation is catastrophically wider than its rationale. A
    back-merge (`git merge main` to keep a branch current) has two parents like any
    other, and its incoming range is EVERY commit the branch had not seen: dozens
    or hundreds, whose trailers landed with their own commits weeks ago. Unioning
    those credits one merge with resolving them, and silently closes any that were
    deliberately left open.

    That range is bounded by the source/target RELATIONSHIP, never structurally, so
    "the close cycle's range is its own story's commits" was never a property the
    code had: a story branch that back-merged `main` carries main's commits in its
    range at close time too.

    UNION, never replace. The authored ids come from a body the operator may have
    written — a `-m` on a hand merge, an edited conflict-finish message, or a
    close-cycle body read back from HEAD — and replacing drops what they typed.

    The bound is the LIVE log, NARROWER than "already recorded": compaction
    archives commit events once their sprint leaves the retention window, and a
    rebased branch's hashes never match, so either case still re-derives. Recorded
    rather than implied — reading the archives here would put an unbounded read on
    a synchronous hook.

    `events` is the caller's already-locked read, so the filter costs no lock.
    """
    recorded = commit_event.recorded_commit_hashes(events)
    unrecorded = [
        body
        for landed, body in commits.merged_range_commits(cwd, commit_hash)
        if landed not in recorded
    ]
    derived, _, _ = commits.extract_resolves_trailer("\n".join(unrecorded))
    return authored + [rid for rid in derived if rid not in authored]


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

    MERGE TAGGING LIVES HERE rather than in either caller. `is_merge` was a
    defaulted parameter exactly one of the two passed, so the dominant hand-merge
    route recorded merge HEADs as plain commits — in the link-rate denominator,
    and drawing a commit-too-large concern for the whole merged branch. The rule
    it now follows: tagging belongs where the parent count is already known.
    """
    if not raw_body:
        return None
    authored, body, has_trailer = parse_commit_body(raw_body)
    resolves = authored

    # Asked for `commit_hash`, not HEAD, so a moved HEAD cannot make this describe
    # a different commit. Absent count (lookup failed, or no hash) leaves the
    # event untagged — the pre-existing behaviour, and the safe direction: an
    # untagged merge is only over-counted in a rate, while a wrongly tagged plain
    # commit would be silently exempt from the size concern the tag suppresses.
    is_merge = False
    if commit_hash:
        parent_count = commits.head_parent_count(cwd, commit_hash)
        is_merge = parent_count is not None and parent_count > 1

    if is_merge and commit_hash:
        resolves = merge_resolves(cwd, commit_hash, resolves, events=events)

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
    #
    # AUTHORED ids only, never the merged-range derivation: an id re-parsed off a
    # commit that landed weeks ago is routinely unresolvable for an innocent
    # reason — a long back-merge's targets were resolved and archived long since
    # — so advising on it files a concern naming closed work. That is why
    # `merge_commit_event` skips this step outright. The advisory stays pointed at
    # what somebody typed, which is the only part they can act on.
    if authored:
        known = resolution.resolvable_event_ids(events)
        unknown = [rid for rid in authored if rid not in known]
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
        is_merge=is_merge,
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


def _a_commit_freshly_landed(cwd: str, commit_hash: str) -> bool:
    """Did a commit land at `commit_hash` a moment ago?

    Returned the KIND until tagging moved into `build_commit_event`, which reads
    the parent count for both callers; with no consumer for the distinction this
    is a yes/no again.

    The two arms stay UNEQUALLY strict, and the merge arm is the stricter: it
    demands the reflog announce a CREATED merge, which is more than the parent
    count the builder tags on. So a fast-forward onto a merge commit is refused
    here, before there is any event to tag.

    Deliberately NOT "did this command make it" — that is what the hook
    cannot prove on this branch. Three signals, all required, because the
    branch is ambiguous without any one of them (a fourth,
    `_message_unreadable_from_command`, guards the caller side):

    * **Fresh.** An old HEAD means the command failed on top of history
      someone else wrote.
    * **Parent count picks the ARM rather than vetoing.** `>1` routes to the
      merge arm, which sets the `is_merge` tag keeping it out of the
      denominator. It does not prove a merge LANDED — a fast-forward onto one
      counts two parents too — so that arm reads the detail as well.
    * **Reflog announces a commit or a created merge.** Freshness and parent
      count both pass for a `rebase (pick)`, an amend, a `reset` onto a young
      commit and a fast-forward, none of which this command produced. Only the
      reflog separates them, so its ABSENCE vetoes rather than letting the
      other two stand alone — an earlier draft degraded to allow there, and
      that was the widest remaining fabrication path.
    """
    facts = commits.head_landing_facts(cwd, commit_hash)
    if facts is None:
        return False
    committer_ts, parent_count, reflog_subject = facts
    # The action names HOW head moved, the detail whether that made a commit.
    action, _, detail = (reflog_subject or "").partition(":")
    action, detail = action.strip(), detail.strip()
    # Bounded at BOTH ends. `now - ts > MAX` alone reads a FUTURE committer date
    # as maximally fresh, so clock skew on the committing host would defeat this
    # guard outright rather than trip it. The housekeeping gate bounds the same
    # helper the same way (`0 <= age`); no grace window here, because unlike a
    # heartbeat a false refusal costs only the trace we recorded before.
    age = time.time() - committer_ts
    if not 0 <= age <= HEAD_REBUILD_MAX_AGE_SECONDS:
        return False
    if parent_count > 1:
        if action == _CONFLICT_FINISH_REFLOG_ACTION:
            return True
        if action.split(maxsplit=1)[:1] != [_MERGE_REFLOG_ACTION]:
            return False
        return detail.startswith(_MERGE_CREATED_DETAIL_PREFIX)
    # Absence VETOES rather than degrading to allow. Degrading left the widest
    # residual fabrication path: with `core.logAllRefUpdates` off, an amend or a
    # reset/ff-merge onto a fresh unrecorded commit, then a failed unreadable
    # commit, satisfies every other guard and records an event for a commit this
    # command did not make — whose trailer then resolves real ids on false
    # evidence. Vetoing costs those repos only the trace they already got before
    # this story, so it is not a regression there; the asymmetry is lopsided.
    # Matches the recorded fail-closed doctrine for an unresolvable `git -C`.
    return action in _COMMIT_REFLOG_ACTIONS


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
    if not _a_commit_freshly_landed(cwd, commit_hash):
        return False
    raw_body = commits.get_commit_message_body(cwd)
    if not raw_body:
        return False
    committed_files = commits.get_committed_files(cwd)
    # No `is_merge` to pass — the builder reads the parent count for both callers.
    # So this path re-reads `%P` that `head_landing_facts` already had. Left
    # redundant rather than threaded back: threading it is exactly what let the
    # other caller forget. The extra read lands on this rare blind-stdout path,
    # never on the hot success path.
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
        review_records.end_review_cycle(
            smm_dir,
            identity.review_watermark_key(cwd),
            identity.review_flags_key(session_cwd),
            commit_hash,
        )
    return True
