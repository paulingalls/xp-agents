#!/usr/bin/env python3
"""The `merge --archive-sprint` step, extracted from close_common.py.

Extracted at the commit that pushed close_common.py over the 500-line cap. It
is the natural seam: a single step in the merge chain whose placement rules and
failure semantics are self-contained, and which the rest of cmd_merge touches
only through one call.

WHERE THE CALLER MUST KEEP IT. The archive is LAST-but-one: after the merge
commit AND the target push, before delete_branch (the one irreversible step).
Both bounds are load-bearing. Later than any step that can still fail, because
sprint.json is the acceptance verify-gate's only input and that gate fails OPEN
without it (close_verify_gate.verify_gate_block) — archiving before a push that
then failed would leave every retry of an unfinished close ungated. Earlier
than the delete, because a failed archive returns nonzero with the source
branch intact, so re-running the identical merge command is safe: the re-merge
is idempotent ("Already up to date"), the re-push is a no-op, the archive
retries.
"""

import sys
from pathlib import Path


def archive_step(smm_dir: Path, smm_preexisting: bool) -> int:
    """Archive sprint.json under *smm_dir*. Returns 0 to continue, 1 to abort.

    *smm_preexisting* must be probed by the caller BEFORE the merge-event
    append, which creates events.jsonl in whatever directory it was handed —
    after that a typo'd --smm-dir is indistinguishable from a real SMM.
    """
    # smm/ is already on sys.path (the caller imports sprint_store from it).
    import sprint_archive

    try:
        archived = sprint_archive.archive(smm_dir)
    except OSError as exc:
        sys.stderr.write(
            f"sprint archive failed after merge; source branch kept for retry: {exc}\n"
        )
        return 1

    if archived is None:
        # Nothing to archive. Never fatal: the merge and push have landed, and
        # no retry makes an absent file appear — but the causes carry opposite
        # weight, so name which one on the evidence available.
        sys.stderr.write(
            f"warn: no sprint.json under {smm_dir} — nothing archived "
            f"({absent_cause(smm_dir, smm_preexisting)})\n"
        )
    else:
        print(f"archived sprint: {archived}")
    return 0


def absent_cause(smm_dir: Path, smm_preexisting: bool) -> str:
    """Why there was nothing to archive, on structural evidence only.

    "Nothing archived" has two causes with opposite weight: a prior attempt of
    this close already archived (the snapshot exists), or the close just ended
    with NO snapshot at all. Neither is knowable for certain from here, so this
    reports the evidence and says which reading it supports — it never asserts
    a cause it cannot see.
    """
    if not smm_preexisting:
        # An SMM always carries events.jsonl, so a directory without one was
        # never an SMM — the cheapest structural tell for a wrong --smm-dir.
        return "not an SMM directory (no events.jsonl) — check --smm-dir"
    import sprint_archive  # lazy for the sys.path reason above

    try:
        newest = sprint_archive.newest_path(smm_dir)
    except sprint_archive.UnusableArchiveError as exc:
        # An unreadable sprints/ is not an empty one. Deliberately routed
        # through newest_path rather than a glob for exactly this: pathlib's
        # globber swallows PermissionError, and reporting "no sprint was ever
        # written" for a directory we simply could not read is the silent-empty
        # failure that module exists to prevent.
        return f"cannot tell which — {exc}"
    if newest is None:
        return "no sprint was ever written here"
    # A prior archive is evidence, not proof. Every past sprint leaves one, so
    # a real-but-WRONG --smm-dir (another project's SMM) looks identical to
    # this close's own retry. Name the file and let the reader settle it.
    return (
        f"already archived by an earlier attempt, if {newest.name} is this "
        "sprint's — otherwise no sprint was written for this close"
    )
