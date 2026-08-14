#!/usr/bin/env python3
"""Best-effort flock: hold it if you can, carry on if you cannot.

One shape for the two callers that want an advisory lock rather than a required
one — `in_place_locks.door_mutex` and `coordination`'s entry writer. They had
drifted into different shapes for the same job: the door yielded a bool from a
contextmanager, while coordination took its caller's `ExitStack` as an
out-parameter and returned a bool, so both of ITS call sites had to remember
`with stack:` afterwards or hold the lock until garbage collection.

PLACEMENT. Not `_append_impl.py`, beside `flock_with_timeout`, even though that is
where it reads most naturally: that file measures at its ceiling, and adding this
crossed it. Not `_append_lock.py` either — this needs `flock_with_timeout`, and
importing it back up is exactly the cycle that file's docstring refuses to open.
So a third module, depending DOWNWARD on `_append_impl` with nothing importing
back. The patch seam `_append_lock.py` protects is untouched, because the budget
is still resolved inside `_append_impl` at acquire time.
"""

import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _append_impl import LockTimeoutError, flock_with_timeout


@contextmanager
def try_flock(
    lock_path: Path,
    *,
    timeout_s: int | None = None,
    on_giveup: Callable[[Exception], None] | None = None,
) -> Iterator[bool]:
    """Hold `lock_path` for the block IF it can be taken. Yields whether it was.

    Never raises on a failed acquire — the caller decides what an unavailable lock
    means for its own work.

    ONLY THE ACQUIRE IS WRAPPED, never the caller's body. Wrapping a whole
    `with flock_with_timeout(...): ...` would catch an `OSError` the BODY raised —
    `write_json_atomic` on a full disk, say — and report it as a lock failure,
    writing a wrong diagnosis into the error log. An exception from the body
    propagates, and the lock is still released.

    `on_giveup` receives the exception that stopped the acquire. It exists because
    a bool cannot carry a CAUSE, and one caller logs it: which errno (`ENOLCK` on
    a network mount) or a timeout is the difference between a diagnosable give-up
    and an unexplained one. The door mutex passes nothing, which is why the
    precedent it set was silent on the point.

    `LockTimeoutError` does not derive from `OSError`, so both are caught and the
    callback is typed on their common base.
    """
    stack = ExitStack()
    try:
        stack.enter_context(flock_with_timeout(lock_path, timeout_s=timeout_s))
    except (LockTimeoutError, OSError) as exc:
        if on_giveup is not None:
            on_giveup(exc)
        yield False
        return
    with stack:
        yield True
