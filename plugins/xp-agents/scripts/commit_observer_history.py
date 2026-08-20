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

import git_head

__all__ = ["is_ancestor", "range_was_rewritten"]

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


# Reflog subjects (`%gs`) whose operation REPLACES commits rather than adding
# them. Matched as prefixes because git appends detail to each: "rebase
# (finish): refs/heads/x onto <sha>", "reset: moving to HEAD~1", "commit
# (amend): <subject>".
#
# Deliberately NOT exhaustive, and the direction of the gap is the point:
# `update-ref` can move a branch anywhere under an operator-supplied message,
# and a shape not listed here goes UNDETECTED — the range records as fresh,
# which is the behaviour that shipped before this module. Adding a looser match
# fails the other way, and that way is unrecoverable: a false decline records
# nothing at all.
_REWRITE_REFLOG_PREFIXES = (
    "rebase",
    "reset:",
    "commit (amend)",
    "filter-branch",
)

# How far back the reflog is read. A branch's log can hold thousands of
# entries, and the scan stops at `last_seen` anyway; this only bounds the
# output of one fork. Past it the leg simply has no opinion, which records —
# see `range_was_rewritten`.
_REFLOG_MAX_ENTRIES = 200


def range_was_rewritten(cwd: str, last_seen: str, head: str) -> bool:
    """True when history INSIDE `last_seen..head` was replaced rather than added.

    Two legs, and both are BOUNDED — the bounds are what make this usable at
    all, because the obvious spelling of each question ("was history rewritten
    here, ever?") measures out as decline-everything on ordinary repositories.

    FAIL DIRECTION, and it is a decision rather than an oversight: positive
    detection declines, absence of a signal RECORDS. A rewrite on a repository
    where neither leg can speak goes undetected and its commits record as
    fresh — today's behaviour, unchanged, rather than a new loss. Read the
    other way, this returns True on every repo with no reflog, which is most of
    them.

    **ORIG_HEAD is sticky.** Git sets it on any rebase, merge or reset and then
    leaves it indefinitely, so its EXISTENCE says nothing: a repo carrying one
    from an ordinary merge months ago would decline every range forever. It is
    a signal only when it is orphaned (not an ancestor of HEAD) AND the orphan
    lay inside our window (`last_seen` is an ancestor of it) — that pair is
    exactly "the rewrite touched commits after the last one we saw".

    **The branch reflog is commonly unusable** — expired (`gc.reflogExpire`, 90
    days by default), absent (a fresh clone, `core.logAllRefUpdates` off), or
    there is no branch at all (detached HEAD). It speaks only when it carries
    an entry naming `last_seen`: without that anchor the scan has no lower
    bound, and a rebase from long before our window would decline a range it
    has nothing to do with.

    Costs at most three forks — two `merge-base --is-ancestor` and one reflog
    read — and only on a reconcile that has unrecorded commits to place. The
    per-Bash common path gains nothing.
    """
    if _orig_head_is_an_orphaned_tip(cwd, last_seen, head):
        return True
    return _reflog_names_a_rewrite(cwd, last_seen)


def _orig_head_is_an_orphaned_tip(cwd: str, last_seen: str, head: str) -> bool:
    """The ORIG_HEAD leg. A plain file read first, so an absent one costs nothing."""
    dirs = git_head.resolve_git_dirs(cwd)
    if dirs is None:
        return False
    orig = _read_object_name(dirs[0] / "ORIG_HEAD")
    if orig is None or orig == head:
        return False
    # Asked in this order so the ordinary case — an ORIG_HEAD still in our
    # history, left by a merge — costs ONE fork rather than two.
    if is_ancestor(cwd, orig, head) is not False:
        return False
    return is_ancestor(cwd, last_seen, orig) is True


def _read_object_name(path: Path) -> str | None:
    """A full object name from a git state file, or None for anything else."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return raw if git_head._OBJECT_NAME_RE.match(raw) else None


def _reflog_names_a_rewrite(cwd: str, last_seen: str) -> bool:
    """The reflog leg: a rewrite operation newer than the entry naming `last_seen`.

    The BRANCH's entries, never `git reflog -1` and never HEAD's own log. `-1`
    describes only the newest entry, which is the veto shape this module's
    docstring forbids; HEAD's log additionally records `checkout` between
    branches, so an ordinary branch switch would read as a rewrite.
    """
    refname = git_head.read_head_ref(cwd)
    if refname is None:
        return False
    try:
        result = subprocess.run(
            [
                "git",
                "reflog",
                "show",
                "--no-abbrev",
                f"--max-count={_REFLOG_MAX_ENTRIES}",
                "--format=%H%x09%gs",
                refname,
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            cwd=cwd,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        entry_hash, _, subject = line.partition("\t")
        if entry_hash == last_seen:
            # The anchor. Everything older than the entry that put the branch
            # at `last_seen` is outside the window this call is asking about.
            return False
        if subject.startswith(_REWRITE_REFLOG_PREFIXES):
            return True
    # Fell off the end without finding the anchor: the log is expired, too
    # short, or was never written for this ref. No opinion, which records.
    return False
