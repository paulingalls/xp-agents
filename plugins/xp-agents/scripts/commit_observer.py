#!/usr/bin/env python3
"""The catch-up observer: commits that moved HEAD while nothing was watching.

`commit_emit.rebuild_at_head` had exactly one caller — inside
`commit_handling._handle_commit`, which `bash_post_tool` reaches only when
`git_commits.is_git_commit(command)` is true. So once a commit-shaped Bash
returned, nothing looked at HEAD again, ever. A commit that lands AFTER that
call returns — the dominant case being `run_in_background: true`, where
PostToolUse fires at LAUNCH — was invisible for good. And since a
`Resolves-Event:` trailer is honored ONLY through `metadata.resolves`, every id
its author named stayed silently open.

This module is that missing observation: on an ordinary (non-commit-shaped)
Bash, compare HEAD against the last one seen in this checkout and record what
appeared in between.

## Its guard is REACHABILITY, not attribution — and that is not a relaxation

`_handle_commit`'s guards (`_a_commit_freshly_landed`,
`_message_unreadable_from_command`) exist to stop the hook claiming *"this
command produced this commit"*. `commit_emit.py`'s comments record exactly what
weakening them cost, and they are LEFT ALONE: this module is a second observer,
not a change to that one.

The observer never makes that claim. Its claim is strictly narrower:

    a commit exists at this hash, reachable from HEAD on this branch, with no
    recorded event — and here is its message read back from git.

Nothing in it is attributed to any command, so the reflog check that separates
"committed" from "rebased/reset/fast-forwarded" answers a question this module
does not ask. Worse, it would make the range walk impossible: `git reflog -1`
describes only the newest entry, so `head_landing_facts` vetoes every commit
older than HEAD by construction.

**Do not "restore" the reflog check here.** It is not a missing guard; it is a
guard for a different claim, and adding it would silently reduce this module to
recording at most the single newest commit.

That rule is about `reflog -1` and about ATTRIBUTION, and it survives a later
change that may look like its opposite: `commit_observer_history` does read the
reflog, but it reads the BRANCH's entries and asks whether history inside the
range was REPLACED — a property of the range, not a claim about who made it.
The veto above fails because one entry cannot describe a range; that read
cannot fail the same way, and it declines the range rather than vetoing every
commit but the newest.

For the same reason this module does NOT borrow the observing Bash's command
string. There is no command to name — an `ls` did not produce the commit it
happens to notice — so the decline records in `commit_observer_reports` identify
the OBSERVER as their source rather than stamping `Command: <some unrelated ls>`
on a commit it had nothing to do with.

## Where it runs, and what it deliberately does not touch

Registered on the NON-commit-shaped branch of `bash_post_tool.run`. A
commit-shaped Bash is already compared against HEAD by `_handle_commit`, which
owns its own decisions there — including the ones it refuses on purpose, such
as a fast-forward. Running both on one call would double-report and would
quietly overturn those refusals on the same tool call that made them.

The last-seen marker is therefore NOT advanced by a commit-shaped Bash, which
is what closes the obvious hole: a backgrounded commit followed immediately by
an ordinary foreground commit leaves the range open across both, so the next
plain Bash still reconciles the one that was missed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _append_impl
import _common
import code_files
import commit_emit
import commit_event
import commit_observer_history
import commit_observer_reports
import commit_observer_state
import commits
import git_head
import markers
import merged_range
from commit_observer_state import read_last_seen_head
from event_schema import METADATA_KEY_COMMIT_HASH

__all__ = [
    "MAX_RECONCILE",
    # Re-exported: the record moved to `commit_observer_state`, but "where did
    # this checkout last see HEAD" is a question about the OBSERVER, and every
    # caller asks it of this module.
    "observe",
    "read_last_seen_head",
]

# How many unrecorded commits may appear between two observations before this
# module declines the whole range and says so.
#
# One backgrounded commit produces one. A handful of foreground commits between
# two plain Bash calls produce a handful. A number well past that is not the
# defect this exists for — it is a branch switch, a fast-forward of somebody
# else's work, or a marker left over from a repo this checkout is not. Those
# ranges reach back into history whose commit events may have been compacted
# out of the LIVE log, and "absent from the live log" is the only test available
# here, so recording them would manufacture duplicate events for work that was
# accounted for weeks ago.
#
# Declining is the safe direction, and the decline is LOUD: see
# `commit_observer_reports.record_range_declined`. Truncating instead would
# report success over a silent cap, which is the failure mode this whole story
# exists to remove.
MAX_RECONCILE = 10


def observe(
    smm_dir: Path, agent_id: str, cwd: str, *, is_xp_agent_leak: bool = False
) -> None:
    """Record every commit that reached HEAD since this checkout was last seen.

    The common path is a handful of small file reads and one string compare:
    HEAD is unchanged on the overwhelming majority of Bash calls, and this
    returns before the event log — or any git subprocess — is touched.
    `git_head.read_head` is a plain read of `.git/HEAD` and the ref it names,
    precisely so that the price of watching every Bash is not a fork per Bash.

    There is deliberately NO fork fallback when the reader cannot answer. Most
    "cannot say" answers are a cwd that is not a repo at all — extremely common
    — and forking there would put the full `git rev-parse` cost on precisely
    the calls with nothing to observe. The cost of the choice is that a repo
    layout `git_head` does not cross goes unobserved, which is the behaviour
    that shipped before this module rather than a new loss.

    A first observation with no marker SEEDS and reconciles nothing: the lower
    bound would otherwise be unbounded and the first Bash of every session
    would walk the repo's whole history.

    The marker advances even when the reconcile DECLINES. A decline that left
    the marker behind would re-file its concern on every subsequent Bash, which
    is how an advisory becomes noise nobody reads.

    It does NOT advance when the reconcile RAISES: that recorded nothing, so
    advancing would silently drop the range this exists to catch. The
    per-commit dedup makes the next Bash's retry resume rather than duplicate.
    That path is the EXPENSIVE one, not a free "leave it open": nothing guards
    this call, so a raise leaves the whole PostToolUse handler — test-run
    detection, the commit nudges and the TDD signals never run for that Bash.
    A failure that needs only the range left open belongs in the quiet `except`
    in the body below, which costs none of that.

    An OWED reset is settled on the very next Bash carrying a usable identity,
    whether or not HEAD moved — that Bash is overwhelmingly one where it did
    not, and waiting for a HEAD move would wait for the next commit, which is
    precisely the commit the reset exists to make the gate see. It is settled
    AFTER the reconcile so that a range whose own DECLINE owes a reset settles
    it on the same call rather than one Bash later, and so a reset owed to an
    older hash is judged against a watermark this call may just have moved.
    """
    head = git_head.read_head(cwd)
    if head is None:
        return
    record = commit_observer_state.read_record(smm_dir, cwd)
    last_seen = commit_observer_state.record_field(
        record, commit_observer_state.MARKER_FIELD
    )
    owed = commit_observer_state.record_field(
        record, commit_observer_state.OWED_RESET_FIELD
    )
    if last_seen is not None and last_seen != head:
        try:
            # `or owed`: rebinding DROPPED a reset still owed from an earlier
            # walk, whenever this one had nothing left to record.
            owed = (
                _reconcile(
                    smm_dir,
                    agent_id,
                    cwd,
                    last_seen,
                    head,
                    is_xp_agent_leak=is_xp_agent_leak,
                )
                or owed
            )
        except (_append_impl.LockTimeoutError, commits.GitUnavailable):
            # Another observer holds the record lock, or a git read never
            # answered. Return WITHOUT advancing, so the next Bash walks the
            # same range — and without raising into the user's Bash call to say
            # so. The git leg joins this one rather than the raise path below
            # BECAUSE of that second half: `bash_post_tool` calls `observe`
            # unguarded, so a raise leaves its `run()` entirely and takes test
            # detection, both commit nudges and the TDD signals with it.
            return
    settled = False
    if owed and not is_xp_agent_leak:
        settled = commit_observer_state.settle_owed_reset(smm_dir, agent_id, cwd, owed)
        if settled:
            owed = None
    if last_seen == head and not settled:
        return
    commit_observer_state.write_record(smm_dir, cwd, head, owed)


def _reconcile(
    smm_dir: Path,
    agent_id: str,
    cwd: str,
    last_seen: str,
    head: str,
    *,
    is_xp_agent_leak: bool,
) -> str | None:
    """Record the unrecorded commits in `last_seen..head`, oldest first.

    Returns the hash whose cycle reset is now OWED, or None when nothing is.
    """
    revs = merged_range.first_parent_range(
        cwd, last_seen, head, limit=MAX_RECONCILE + 1
    )
    if revs is None:
        commit_observer_reports.record_range_declined(
            smm_dir,
            agent_id,
            head,
            f"git could not describe the range {last_seen[:12]}..{head[:12]}. "
            "Either the last-seen commit is unknown to this checkout — "
            "rewritten by a rebase, garbage-collected, or written by another "
            "repository — or git could not be run here at all.",
        )
        return None
    if len(revs) > MAX_RECONCILE:
        commit_observer_reports.record_range_declined(
            smm_dir,
            agent_id,
            head,
            f"more than {MAX_RECONCILE} commits appeared since {last_seen[:12]}. "
            "That is a branch switch or a fast-forward of history authored "
            "elsewhere, not a commit this session made, so NONE of the range was "
            "recorded and any resolve trailer on it is unlinked.",
        )
        return None

    # The cheap pre-check, outside the lock: most ranges here are fully recorded.
    events, _ = _common.load_events_with_resolutions(smm_dir)
    already = commit_event.recorded_commit_hashes(events)
    pending = [rev for rev in revs if rev not in already]
    if not pending:
        return None

    # EVERY git call this module added sits below this line, and that placement
    # is a budget rather than a preference: `observe` runs on every ordinary
    # Bash, a sibling hook path is bounded at 5s, and one unbudgeted git read
    # has already broken that bound once this sprint. Above here the cost is a
    # HEAD read, a marker read and a string compare; the rare reconcile that
    # reaches here adds at most three forks (two `merge-base --is-ancestor`,
    # one reflog read), plus one more on the owed-reset path in `observe`.
    #
    # Declined WHOLESALE, matching the two declines above rather than inventing
    # a third shape. The alternative — per-commit `patch-id` identity — asks a
    # question this module has no way to bound.
    if commit_observer_history.range_was_rewritten(cwd, last_seen, head):
        commit_observer_reports.record_range_declined(
            smm_dir,
            agent_id,
            head,
            f"history after {last_seen[:12]} was rewritten. The hashes now in "
            "the range are new ones for work already recorded under the old "
            "ones, so recording them would apply their trailers twice and "
            "advance the review watermark past unreviewed work. NONE of the "
            "range was recorded.",
        )
        # The marker still advances on a decline, so `_end_cycle_for_the_range`
        # below never runs for this range and `quality_review_done` stays
        # latched — which is the very defect the owed reset exists for, reached
        # by a new route. Owed to HEAD rather than to anything inside the range:
        # every commit in it is one this observer just refused to record, so a
        # reset to one would point the gate's `{sha}..HEAD` diff at a commit
        # carrying no event.
        return head
    review_cadence = markers.read_review_cadence(smm_dir)
    newest_recorded: str | None = None

    # CLOSES: two observers sharing a checkout, both reading the same snapshot
    # and both appending the same commit. The read above cannot see an append
    # landing after it returns, so the dedup is re-derived inside the lock.
    #
    # DOES NOT CLOSE: `commit_handling._handle_commit` writes commit events
    # without this lock, so an observer racing a COMMIT-shaped Bash in a
    # sibling process can still double-record. That needs both writers to take
    # it — a change this module deliberately leaves alone. Said out loud: an
    # undocumented partial fix reads as a complete one.
    with commit_observer_state.observer_lock(smm_dir):
        # REBOUND, not merely re-read: `_record_one` mutates this list in place
        # so a merge later in the range sees earlier appends, and the pre-lock
        # snapshot would derive its trailers from a log that has since moved.
        events, _ = _common.load_events_with_resolutions(smm_dir)
        recorded = commit_event.recorded_commit_hashes(events)
        for rev in pending:
            if rev in recorded:
                continue
            if _record_one(
                smm_dir,
                agent_id,
                cwd,
                rev,
                events=events,
                review_cadence=review_cadence,
            ):
                recorded.add(rev)
                newest_recorded = rev

        # One reset for the range — the same effect `rebuild_at_head` owns, for
        # the same reason: a commit event recorded without it leaves the previous
        # cycle's quality-review flag latched, so the next commit's gate reads
        # satisfied off a review that predates this commit. Skipped on a leaked
        # xp- agent_type exactly as both other commit paths skip it: recording
        # the commit is always right, mutating cycle state under a wrong identity
        # is not. INSIDE the lock: released first, a slower observer's older hash
        # lands after a faster one's and walks the watermark backwards.
        #
        # OWED, not dropped, when the identity is wrong. Skipping the reset is
        # the deliberate part; losing it is not, and it WAS lost — the marker
        # advanced past the skip, so the range never came back and
        # `quality_review_done` stayed latched for good. Returning it up to
        # `observe` rather than simply not advancing the marker, because that
        # naive fix deadlocks: the next walk finds everything already recorded,
        # hits the `if not pending` exit above, and never reaches this line
        # again.
        if newest_recorded is None:
            return None
        newest = commit_observer_state.newest_recorded_in_range(revs, recorded)
        if newest is None:
            return None
        if is_xp_agent_leak:
            return newest
        commit_observer_state.end_cycle_for(smm_dir, cwd, newest)
    return None


def _record_one(
    smm_dir: Path,
    agent_id: str,
    cwd: str,
    rev: str,
    *,
    events: list[dict],
    review_cadence: str,
) -> bool:
    """Build and append the commit event for `rev`. False when it was declined.

    `build_commit_event` is reused rather than reimplemented: the sequence it
    owns — trailer extraction, the Co-Authored-By strip, the unlinkable-trailer
    advisory, sprint load, story attribution, merge and free-branch and cadence
    tagging — is what makes the trailer resolve at all, and copying it is how
    the third emitter drifted three ways.
    """
    raw_body = commits.get_commit_message_body(cwd, rev)
    committed_files = commits.get_commit_files(cwd, rev)
    event = commit_emit.build_commit_event(
        smm_dir,
        agent_id,
        cwd,
        raw_body,
        rev,
        events=events,
        committed_files=committed_files,
        code_file_count=code_files.count_code_files(committed_files),
        review_cadence=review_cadence,
        # The one caller: nothing was watched, so nothing may be attributed.
        from_commit_only=True,
    )
    if event is None:
        commit_observer_reports.record_declined(
            smm_dir, agent_id, rev, "git would not return its message"
        )
        return False
    if not _append_or_raise(smm_dir, event):
        commit_observer_reports.record_declined(
            smm_dir, agent_id, rev, "the event log refused the event"
        )
        return False
    # So a later commit in the SAME range is not read against a stale log: a
    # merge later in the range rebuilds its own recorded-hash index off this
    # list, and would otherwise re-derive trailers from a commit just recorded.
    events.append(event)
    return True


def _append_or_raise(smm_dir: Path, event: dict) -> bool:
    """True when the event reached the log; False when it never can.

    `bulk_append_safe` logs a lock timeout and returns, so its caller cannot
    tell a written event from a dropped one — and a dropped one that advanced
    the marker is a commit no event will ever carry. Split by what a retry could
    change: a lock timeout RAISES, leaving the range open for the next Bash,
    while an invalid or oversize event is permanent and is reported against its
    own hash. Its debt probe is not lost; that no-ops for a commit event. Its
    hook_errors trace is kept by hand, so a wedged lock still leaves one.
    """
    try:
        _append_impl.bulk_append(smm_dir, [event])
    except _append_impl.LockTimeoutError as e:
        _common.log_hook_error(
            f"commit observer left {_hash_of(event)[:12]} unrecorded: {e}",
            error_class=type(e).__name__,
        )
        raise
    except ValueError:
        return False
    return True


def _hash_of(event: dict) -> str:
    """The event's commit hash, for a diagnostic that must not raise itself."""
    return str(event.get("metadata", {}).get(METADATA_KEY_COMMIT_HASH, "?"))
