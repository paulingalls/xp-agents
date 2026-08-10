#!/usr/bin/env python3
"""Whole-file rewriting of events.jsonl — the merge that makes it safe.

Split out of ``_append_impl.py`` to keep that file under its line-count band.
The appender's job is to ADD one event under lock; this module's job is the
opposite shape — a caller hands over a snapshot of what should survive and the
file is replaced wholesale. Those are two responsibilities, and the merge rule
below is the whole reason the second one is not simply "write the snapshot".

Re-exported BY IDENTITY from ``_append_impl`` (see the import at the bottom of
that module), so every existing ``from _append_impl import replace_events_file``
and ``_append_impl.replace_events_file`` reference resolves unchanged — the same
contract ``_append_lock.py`` is held to.

``flock_with_timeout`` is imported LAZILY inside ``replace_events_file`` rather
than at module level, and that is not a style choice: ``_append_impl`` imports
this module at load time for the identity re-export, so a module-level import
back up here would close a cycle — whichever of the two is imported first, the
second sees a half-initialized module and the from-import raises. The
``LOCK_TIMEOUT_SECONDS`` patch seam is unaffected either way: it lives in
``_append_impl``'s own namespace, which is where ``flock_with_timeout`` reads it
from regardless of how this module got hold of the function.
"""

import contextlib
import json
import os
import tempfile
from pathlib import Path

__all__ = ["_preservable_id", "event_ids", "replace_events_file"]


def event_ids(events: list[dict]) -> set[str]:
    """The ids of *events* — the `seen_ids` a whole-file rewriter must pass.

    Skips entries with no usable string id; `parse_jsonl` admits any dict, so
    a hand-edited line can reach a caller without one. Such an entry is still
    written if the caller retained it — it is only unmatchable when scanning
    the file, which is what the id-less DROP rule in `replace_events_file`
    covers.
    """
    return {e["id"] for e in events if isinstance(e.get("id"), str)}


def _preservable_id(line: str) -> str | None:
    """The id of a file line that a rewriter could have SEEN, else None.

    None means the line is not preservable and is dropped: it is malformed, is
    not an object, or carries no string id. Dropping it is SAFE because of that
    missing id — every event built for `append_event` gets a `generate_id()`
    id, so an id-less line was never a concurrent arrival. The guarantee is the
    BUILDERS', not validation's: `append_event` does not call `validate_event`
    and neither do all of its callers, so an append path that can omit `id`
    would break this rule. Dropping is also NECESSARY: an unpreservable line
    can never be in any `seen_ids`, so a naive preserve-the-unseen rule would
    keep it forever and `repair` could never delete a malformed line again.
    """
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    event_id = obj.get("id")
    return event_id if isinstance(event_id, str) else None


def replace_events_file(
    smm_dir: Path, events: list[dict], *, seen_ids: set[str]
) -> str:
    """Read events.jsonl under exclusive flock, replace atomically.

    *events* is the caller's snapshot of what should survive — but the caller
    read it WITHOUT the exclusive lock, so the file may have grown since. An
    event appended in that window is in neither the snapshot nor the archive
    the caller built from it; writing the snapshot verbatim would erase it
    with no trace anywhere. So the read this function already does under the
    lock is not thrown away: it is merged.

    *seen_ids* is what makes the merge decidable — the ids the caller actually
    LOOKED AT. Every file line is then one of four things:

      * seen and retained     -> written (the caller's copy, so a rewriter such
                                 as `migrate` keeps its transformation)
      * seen and NOT retained -> dropped, deliberately (archived, invalid, a
                                 duplicate) — the fix must not resurrect these
      * NOT seen              -> PRESERVED at the tail: an event the caller
                                 never saw was never a candidate for removal
      * unpreservable         -> dropped; see `_preservable_id`

    Keyword-only and REQUIRED on purpose: a caller that forgets it is a
    TypeError, not a silent return to eating events.

    Preserved lines are written back BYTE-FOR-BYTE rather than re-serialized —
    this function has no business rewriting an event it does not understand.

    Returns the original file contents (for callers that back up the original).
    Raises LockTimeoutError if the lock cannot be acquired.
    """
    # Lazy by necessity — see the module docstring: `_append_impl` imports this
    # module for the identity re-export, so a module-level import would cycle.
    from _append_impl import flock_with_timeout

    events_file = smm_dir / "events.jsonl"
    lock_file = smm_dir / "events.lock"
    original_content = ""

    with flock_with_timeout(lock_file):
        # Read original under lock (prevents TOCTOU race)
        try:
            original_content = events_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            original_content = ""

        # Events that arrived while the caller was deciding — keep them.
        unseen: list[str] = [
            stripped
            for line in original_content.splitlines()
            if (stripped := line.strip())
            and (event_id := _preservable_id(stripped)) is not None
            and event_id not in seen_ids
        ]

        # Write replacement via tempfile + rename
        lines = [json.dumps(e, ensure_ascii=False) for e in events] + unseen
        fd, tmp = tempfile.mkstemp(dir=smm_dir, suffix=".jsonl.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))
            os.chmod(tmp, 0o600)
            os.rename(tmp, events_file)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    return original_content
