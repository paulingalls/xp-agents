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
