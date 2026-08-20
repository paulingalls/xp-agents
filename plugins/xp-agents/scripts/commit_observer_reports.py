#!/usr/bin/env python3
"""What the catch-up observer says when it cannot record what it can see.

Split from `commit_observer.py` at its recorded 450-line sub-cap. The line is
the module's own: `commit_observer` decides WHAT is recordable, this decides
what is SAID about the part that is not. Every function here ends in a concern
on the event log and none of them touches a marker, git, or the commit path.

The shape they share, and the reason they are one module rather than three
`append_safe` calls at three call sites: a decline must be as visible as a
success or it reproduces, one module over, the exact silence the observer
exists to end — a commit that reached HEAD and no event ever named.
"""

import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
from event_schema import METADATA_KEY_COMMIT_HASH

__all__ = [
    "OBSERVER_SOURCE",
    "record_declined",
    "record_owed_reset_dropped",
    "record_range_declined",
]

# Why no command is named. The observer never claims a command produced the
# commit it noticed — an `ls` did not — so stamping `Command: <some unrelated
# ls>` on the record would assert exactly the attribution the observer refuses.
OBSERVER_SOURCE = (
    "Recorded by the post-Bash commit observer, which compares HEAD against "
    "the last one it saw in this checkout. No command is named because none "
    "was observed making it."
)


def record_declined(smm_dir: Path, agent_id: str, rev: str, why: str) -> None:
    """A commit reachable from HEAD that no event will carry is reported.

    AC3: a declined reconcile is distinguishable from a successful one — a
    CONCERN carrying the hash, where a success is a COMMIT event carrying it.
    The backgrounded case recorded NEITHER, which is the defect being fixed; a
    new silent path here would reproduce it one module over.
    """
    append_concern(
        smm_dir,
        agent_id,
        f"A commit at {rev[:12]} is reachable from HEAD with no recorded event, "
        f"and {why}, so nothing was recorded for it. Any resolve trailer on it "
        f"is unlinked. {OBSERVER_SOURCE}",
        metadata={METADATA_KEY_COMMIT_HASH: rev},
    )


def record_range_declined(smm_dir: Path, agent_id: str, head: str, reason: str) -> None:
    """The whole range was refused. Say which range, and why."""
    append_concern(
        smm_dir,
        agent_id,
        f"Commit reconciliation declined at HEAD {head[:12]}: {reason} "
        f"{OBSERVER_SOURCE}",
        metadata={METADATA_KEY_COMMIT_HASH: head},
    )


def record_owed_reset_dropped(smm_dir: Path, agent_id: str, owed: str) -> None:
    """A review-cycle reset that was owed and can no longer be placed.

    Owed because the observation that earned it ran under a leaked identity;
    unplaceable because git can no longer resolve the hash it was owed to — a
    rebase or a prune took it. Kept, it wedges the observer's marker forever
    AND leaves the latched review flag it exists to clear fully live; dropped
    in silence, the unreviewed commit that follows is the one thing nobody
    hears about. So it goes, and says so, exactly once.
    """
    append_concern(
        smm_dir,
        agent_id,
        f"A review-cycle reset owed to commit {owed[:12]} was dropped: git can "
        f"no longer resolve that commit, so there is no safe hash to reset to. "
        f"A quality-review flag may still be set from a review that predates "
        f"the work that commit carried — run /xp-quality-review before the next "
        f"commit rather than trusting the gate. {OBSERVER_SOURCE}",
        metadata={METADATA_KEY_COMMIT_HASH: owed},
    )


def append_concern(
    smm_dir: Path, agent_id: str, content: str, *, metadata: dict
) -> None:
    """Never raise: an observation must not break the user's Bash call."""
    with contextlib.suppress(OSError, ValueError):
        _common.append_safe(
            smm_dir,
            concerns.make_concern(content, "low", agent_id, metadata=metadata),
        )
