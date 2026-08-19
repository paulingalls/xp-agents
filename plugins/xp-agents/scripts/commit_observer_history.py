#!/usr/bin/env python3
"""What git says about this checkout's history — the observer's ancestry reads.

Separate from `commit_observer` because the two answer different questions and
are paid for at different times. The observer decides what to record; this
answers "where does this commit sit relative to that one", which is the only
question in the module that costs a fork.

EVERY function here forks git, so every caller must keep it off the per-Bash
common path. `commit_observer.observe` runs on every ordinary Bash and the
overwhelming majority of those answer "HEAD did not move" from file reads
alone; a fork added above that exit is a fork on every tool call the session
makes. The budget is stated where the calls are made.

Shipped plugin code reading SOMEONE ELSE'S git: no xp-agents history, no
project language, no repository configuration is assumed. `git merge-base` is
in every git that has shipped this decade and answers about commit objects
only, which is why the ancestry question is spelled that way rather than by
parsing a log.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

__all__ = ["is_ancestor"]

# Per call, matching `commits._run_git`. The callers are on the rare reconcile
# path, never the per-Bash one, and each states its own call count.
_TIMEOUT_SECONDS = 5


def is_ancestor(cwd: str, maybe_ancestor: str, descendant: str) -> bool | None:
    """True/False/None — and the None is the whole reason this is not a bool.

    `git merge-base --is-ancestor` exits 0 for yes, 1 for no, and 128 when it
    cannot resolve one of the revisions at all. Collapsing 128 into "no" is
    what every convenience wrapper does and is wrong for both callers here: a
    revision git has never heard of means a hash that was rewritten or pruned
    out from under us, and that is a case to REPORT, not to answer with a
    confident "not an ancestor". `commits._run_git` cannot be reused for the
    same reason — it returns None for any non-zero status, so 1 and 128 arrive
    indistinguishable.

    A commit is its own ancestor, so `is_ancestor(x, x)` is True. Callers that
    need a STRICT descendant compare the hashes themselves; both of ours want
    to treat "already there" as its own case and do exactly that.
    """
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", maybe_ancestor, descendant],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            cwd=cwd,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    match result.returncode:
        case 0:
            return True
        case 1:
            return False
        case _:
            return None
