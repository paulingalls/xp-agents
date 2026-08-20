#!/usr/bin/env python3
"""This checkout's observation record, and the review-cycle reset it may owe.

Split from `commit_observer.py` when the owed reset pushed it through its
recorded 450-line sub-cap. The line is between WALKING a range and the state
that walk reads and leaves behind: everything here is the per-checkout record,
the lock that serialises writers of it, and the one deferred action it carries.
Nothing here reads a commit message or appends a commit event.

The record is a single marker holding two fields, one file on purpose — see
`_OWED_RESET_FIELD`. Both are keyed on the REPO rather than the session,
because a checkout outlives every session that visits it.
"""

import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _append_impl
import commit_observer_history
import commit_observer_reports
import identity
import markers
import review_records

__all__ = [
    "MARKER_FIELD",
    "OWED_RESET_FIELD",
    "end_cycle_for",
    "newest_recorded_in_range",
    "observer_lock",
    "read_last_seen_head",
    "read_record",
    "record_field",
    "settle_owed_reset",
    "write_record",
]

MARKER_FIELD = "head"

# The reset a leaked observation could not apply, carried in the SAME record as
# the head above rather than in a file of its own.
#
# Its own file would be the obvious shape and costs a second marker read on
# every Bash in the session — the one path this module is built to keep down to
# file reads and a string compare. This record is already read there, is already
# keyed per checkout, and is already the one marker deliberately absent from
# `markers._AGENT_SCOPED_MARKERS`: an owed reset swept at session end would die
# at exactly the boundary it exists to survive, since the leaked Bash and the
# clean one that settles it are routinely in different sessions.
OWED_RESET_FIELD = "owed_reset"

# The observer's OWN lock file, never the event log's. `flock` conflicts
# between two open file descriptions in the same process, so taking the events
# lock while holding it — `bulk_append_safe` takes it per append — would
# deadlock this hook against itself.
_LOCK_FILE = ".commit-observer.lock"

# Short on purpose. `flock_with_timeout`'s own docstring names this case: a
# best-effort advisory file, where blocking a synchronous hook for the event
# log's 10s is its own problem. On expiry the range simply stays open.
_LOCK_TIMEOUT_SECONDS = 2


def _marker_key(cwd: str) -> str:
    """Which checkout's HEAD this is. The keying the commit path already uses.

    Per repo/worktree, never per session: the SMM is shared across worktrees,
    and a teammate's commits move ITS head, not the lead's. Sharing one marker
    would make every worktree look to every other like a giant unexplained
    jump — and then get declined by the cap above, forever.
    """
    return identity.review_watermark_key(cwd)


def read_record(smm_dir: Path, cwd: str) -> dict:
    """This checkout's observation record — THE read on the per-Bash path.

    One read for both fields. Reading them separately would double the cost of
    the path whose whole design is that nothing happened on it.
    """
    data = markers.marker_read(smm_dir, markers.LAST_SEEN_HEAD, _marker_key(cwd))
    return data if isinstance(data, dict) else {}


def record_field(record: dict, field: str) -> str | None:
    """A hash-valued field, or None for missing, empty, or the wrong type."""
    value = record.get(field)
    return value if isinstance(value, str) and value else None


def read_last_seen_head(smm_dir: Path, cwd: str) -> str | None:
    """The HEAD this checkout was last observed at, or None when never seen."""
    return record_field(read_record(smm_dir, cwd), MARKER_FIELD)


def write_record(
    smm_dir: Path, cwd: str, commit_hash: str, owed_reset: str | None
) -> None:
    """Both fields, always together.

    `owed_reset=None` OMITS the key rather than storing a null, so a record
    with nothing owed is byte-identical to one written before this field
    existed — which is what an upgrading install reads on its first Bash.
    """
    record = {MARKER_FIELD: commit_hash}
    if owed_reset:
        record[OWED_RESET_FIELD] = owed_reset
    with contextlib.suppress(OSError, ValueError):
        markers.marker_write(
            smm_dir,
            markers.LAST_SEEN_HEAD,
            record,
            _marker_key(cwd),
        )


def settle_owed_reset(smm_dir: Path, agent_id: str, cwd: str, owed: str) -> bool:
    """Apply or drop a reset a leaked observation could not apply. True = done.

    False means "still owed", and the `except` that returns it wraps the WHOLE
    locked body, not just the acquire: the lock being busy or unopenable, and
    equally a watermark read, an ancestry fork, a dropped-reset record or the
    cycle end itself failing on I/O. That breadth is deliberate — what those
    share is that a RETRY could change the answer, which is the only question
    this return value asks. Every answer the body actually REACHES resolves the
    record, because a reset kept across an answer it cannot use wedges the marker
    forever while leaving the latch defect it exists to fix fully live. Nothing
    may escape either way: this call sits outside `observe`'s own `except`, and
    its caller runs that unguarded.

    THREE states, all ruled here rather than left to discovery:

    * **No watermark at all.** `REVIEW_WATERMARK` *is* agent-scoped and swept
      at session end, so this is the ordinary cold start and there is nothing
      to walk backwards over. Apply.
    * **Already at the owed hash.** That reset happened; a second one would
      clear the flags a review has set since and demand a re-review nobody
      asked for. Drop.
    * **Otherwise drop it only when the watermark is strictly PAST it.**
      Walking the watermark backwards is the defect commit `86d4d129` fixed
      earlier this sprint, and an owed reset is a new door onto exactly it —
      but "not a descendant of the watermark" is not the same claim as "older
      than the watermark", and reading it as one threw the reset away after
      every rebase. `_watermark_is_ahead` separates them.

    The fourth answer is git's "I have never heard of that revision", which is
    why `is_ancestor` is three-valued: the owed hash was rewritten or pruned
    away — increment 3's own rewrite specimen can do it — and that is a loss to
    REPORT, not one to answer with a confident "not a descendant".

    At most TWO forks, and only when a reset is genuinely owed, which is never
    the common path: the second is asked only when the first says "not a
    descendant", which is itself the rare answer.
    """
    watermark_key = identity.review_watermark_key(cwd)
    try:
        with observer_lock(smm_dir):
            # Re-read INSIDE the lock, like `_reconcile`'s dedup: a reconcile
            # landing between the read and the write is exactly the concurrent
            # writer whose newer hash this must not overwrite with an older one.
            watermark = review_records.read_review_watermark(smm_dir, watermark_key)
            if watermark and owed == watermark:
                return True
            if watermark:
                verdict = commit_observer_history.is_ancestor(cwd, watermark, owed)
                if verdict is None:
                    commit_observer_reports.record_owed_reset_dropped(
                        smm_dir, agent_id, owed
                    )
                    return True
                if verdict is False and _watermark_is_ahead(cwd, watermark, owed):
                    return True
            review_records.end_review_cycle(
                smm_dir, watermark_key, identity.review_flags_key(cwd), owed
            )
    except (_append_impl.LockTimeoutError, OSError):
        return False
    return True


def _watermark_is_ahead(cwd: str, watermark: str, owed: str) -> bool:
    """Is the watermark strictly PAST the owed hash — the one safe drop?

    `is_ancestor(watermark, owed)` answering False covers two different
    histories: the owed commit is OLDER, so a review has since ended at a
    descendant of it and the reset already happened at a newer hash; or the two
    DIVERGED, because a rebase left the watermark on a line HEAD no longer
    reaches. Only the first is superseded. Dropping on the second discarded the
    reset in precisely the state it was invented for, with no reset applied and
    no trace filed, so the reverse question is asked before dropping.

    Anything but a confident "yes, older" APPLIES, including git failing to
    answer: over-applying costs one re-review, while under-applying leaves
    `quality_review_done` latched and the next commit's gate reads satisfied off
    a review that predates a rebase.
    """
    return commit_observer_history.is_ancestor(cwd, owed, watermark) is True


def newest_recorded_in_range(revs: list[str], recorded: set[str]) -> str | None:
    """The NEWEST commit in the range the log now carries.

    Not whichever of them this observer recorded: a foreground commit that
    already ended its own cycle sits at the top of the same range (the
    backgrounded case, one commit later), so keying the reset to the older hash
    walks the watermark BACKWARDS over it and clears the review that ran in
    between.
    """
    return next((rev for rev in reversed(revs) if rev in recorded), None)


def end_cycle_for(smm_dir: Path, cwd: str, newest: str) -> None:
    """End the cycle for `newest`. A watermark already there means it happened."""
    watermark_key = identity.review_watermark_key(cwd)
    if newest == review_records.read_review_watermark(smm_dir, watermark_key):
        return
    review_records.end_review_cycle(
        smm_dir, watermark_key, identity.review_flags_key(cwd), newest
    )


def observer_lock(smm_dir: Path) -> "contextlib.AbstractContextManager[None]":
    """Serialize this checkout's observers around the read-check-append.

    Held across `_record_one`'s git reads, which is bounded on purpose: only
    the rare path reaches here, only other observers contend, and
    `MAX_RECONCILE` caps the walk. Building outside the lock instead would
    derive merge trailers from the snapshot the lock exists to invalidate.
    """
    return _append_impl.flock_with_timeout(
        smm_dir / _LOCK_FILE, timeout_s=_LOCK_TIMEOUT_SECONDS
    )
