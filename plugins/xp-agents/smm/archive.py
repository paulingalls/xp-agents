#!/usr/bin/env python3
"""Never-clobbering archive writes for the whole-file rewriters.

`compact` and `repair` both MOVE events out of events.jsonl: compact deletes
what it archived, repair drops the bad lines it backed up. So the file under
`backups/` is not a convenience copy — it is the ONLY copy of what was removed.

A name stamped at one-second resolution cannot carry that weight. Two runs in
the same second compute the same name, and a plain write silently overwrites
the first run's only copy: its events are then gone from events.jsonl AND gone
from backups/ — annihilated, with no trace and no signal. That is the exact
failure the rewriters' `seen_ids` merge exists to prevent, one layer out, and
same-second runs are ordinary rather than exotic (every teammate compacts at
SessionEnd, and they finish together).

So the name is CLAIMED, not assumed: `O_CREAT | O_EXCL` fails rather than
opens when the file already exists, and a counter breaks the tie. The
uncontended name is unchanged (`archive-{ts}.jsonl`), so only a real collision
ever grows a suffix.
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

# Bound on same-second collisions before we refuse to guess. Reaching this means
# something is very wrong (a thousand rewrites in one second); losing the archive
# is worse than raising, so it raises.
MAX_COLLISIONS = 1000


def write_archive(backups_dir: Path, prefix: str, content: str) -> Path:
    """Write *content* to `backups/{prefix}-{ts}.jsonl`, never overwriting.

    Returns the path actually written. On a same-second collision, appends
    `-1`, `-2`, ... until a name is free.

    Raises OSError if no free name exists within MAX_COLLISIONS — deliberately
    LOUD. The caller is about to delete the events this content is the only copy
    of; silently dropping the archive is the one outcome worse than failing.
    """
    backups_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    for collision in range(MAX_COLLISIONS):
        suffix = "" if collision == 0 else f"-{collision}"
        path = backups_dir / f"{prefix}-{ts}{suffix}.jsonl"
        try:
            # O_EXCL is the whole point: claim the name or fail, never truncate.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    raise OSError(
        f"Could not claim an archive name under {backups_dir} after "
        f"{MAX_COLLISIONS} collisions on {prefix}-{ts}; refusing to overwrite "
        "an existing archive, which may be the only copy of removed events."
    )


def archive_json(
    smm_dir: Path, src_filename: str, dest_subdir: str, prefix: str
) -> Path | None:
    """Move smm_dir/src_filename to smm_dir/dest_subdir/{prefix}_{ts}.json.

    Never overwrites an existing destination.

    Returns the archived path, or None if the source does not exist. On a
    same-second collision the name grows a -1, -2, ... suffix (O_EXCL claim),
    so a second archive in the same second never clobbers the first.
    """
    src = smm_dir / src_filename
    dest_dir = smm_dir / dest_subdir
    dest_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    for collision in range(MAX_COLLISIONS):
        suffix = "" if collision == 0 else f"-{collision}"
        dest = dest_dir / f"{prefix}_{ts}{suffix}.json"
        try:
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        os.close(fd)  # claim only; move replaces the empty placeholder
        try:
            shutil.move(str(src), str(dest))
        except FileNotFoundError:
            dest.unlink(missing_ok=True)  # source vanished — leave no empty placeholder
            return None
        except OSError:
            # ANY other failure (permissions, a full or read-only destination,
            # a cross-device copy that dies mid-way) must clear the claim too.
            # A surviving 0-byte file carries a real snapshot's name, so every
            # later reader takes it for a valid archived sprint/plan — and the
            # next same-second archive skips that name and files the REAL
            # snapshot under a -1 suffix beside the empty one.
            dest.unlink(missing_ok=True)
            raise
        return dest
    raise OSError(
        f"Could not claim an archive name under {dest_dir} after "
        f"{MAX_COLLISIONS} collisions on {prefix}_{ts}; refusing to overwrite "
        "an existing snapshot."
    )


def find_in_archives(backups_dir: Path, event_id: str) -> tuple[Path, dict] | None:
    """The archived copy of *event_id*, or None. Newest archive wins.

    The read side of this module's invariant: what the rewriters moved here is
    the ONLY copy, and an id stays citable in `references` and
    `metadata.resolves` long after compaction takes it out of events.jsonl. A
    lookup that stops at the live log therefore reports DELETION where there
    was only relocation — which is not a hypothetical: it produced an hour of
    wrong diagnosis and two retracted events in this project's own log.

    Ordered by MTIME, not by name. `backups/` mixes `archive-*`, legacy
    `events-*` and `pre-repair-*`, plus `-N` collision suffixes, so a lexical
    sort is not chronological — `pre-repair-2026...` sorts before
    `archive-2026...` while being the newer file. A pre-repair backup is a
    whole-file copy, so one id genuinely lives in several archives and the
    order decides which version the reader gets.

    Parsed tolerantly, via the canonical JSONL reader: a repair archive holds
    malformed lines BY CONSTRUCTION — dropping them is why it exists — so a
    per-line json.loads would raise on exactly the files most likely to carry
    a recovered id.

    Exact ids only. Prefix resolution stays with the live-log lookup, whose
    ambiguity rule is defined over one file; an archive scan cannot see the
    whole id space at once, so a prefix that is unique here may not be unique
    overall.
    """
    if not backups_dir.is_dir():
        return None

    import append_validation

    archives = [p for p in backups_dir.glob("*.jsonl") if p.is_file()]
    for path in sorted(archives, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        events, _ = append_validation.parse_jsonl(raw)
        for event in events:
            if event.get("id") == event_id:
                return path, event
    return None
