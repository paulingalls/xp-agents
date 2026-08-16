#!/usr/bin/env python3
"""Which commits a RANGE contains — the two range questions the hooks ask.

Split from `commits.py`, which crossed its 450-line sub-cap when the per-commit
reader arrived, and stayed split when the second range question arrived for the
same reason. Both are `git rev-list`/`git log` walks whose subtlety is in the
revision arguments, so they live together rather than beside every other git
read.

* `merged_range_commits` — what a MERGE brought in, for the merge emitters.
* `first_parent_range` — what moved HEAD on THIS branch between two revisions,
  for `commit_observer`'s catch-up walk.

They are near-opposites and must not be confused: the first deliberately
crosses into the merged branch, the second deliberately refuses to.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from commits import _run_git

# A full git object name. Anchored at both ends, because its whole job is to
# refuse a hash-shaped span a commit BODY supplied — see the parse below.
_OBJECT_NAME_RE = re.compile(r"^[0-9a-f]{40}$")


def first_parent_range(
    cwd: str, base: str, head: str, *, limit: int
) -> list[str] | None:
    """Commits on `head`'s first-parent chain that `base` cannot reach, oldest first.

    None when git cannot answer — which is the meaningful case, not an empty
    one: `base` unknown to this repo (rewritten by a rebase, garbage-collected,
    or a marker written by another checkout) is a state the caller must report,
    while "nothing new" is a legitimate empty list.

    Every commit returned is reachable from `head` BY CONSTRUCTION — that is
    what `base..head` means — so this query IS `commit_observer`'s reachability
    guard, asked once for the range instead of once per commit.

    `--first-parent` is load-bearing, and this is where it differs from
    `merged_range_commits` directly above. Without it a back-merge enumerates
    every commit the merged branch brought in: dozens whose own events landed
    weeks ago and may since have been compacted out of the LIVE log, which is
    the only index a caller can dedup against — so it would re-record them. The
    first-parent chain is what moved HEAD *here*, which is the question asked.

    `limit` bounds the walk. Pass one MORE than you will accept, so an over-long
    range is visible as such rather than silently truncated: git applies the
    count to the newest commits before `--reverse` orders them.
    """
    out = _run_git(
        [
            "git",
            "rev-list",
            "--first-parent",
            "--reverse",
            f"--max-count={limit}",
            f"{base}..{head}",
        ],
        cwd,
    )
    if out is None:
        return None
    return out.split()


def merged_range_commits(cwd: str, merge_hash: str) -> list[tuple[str, str]]:
    """``(hash, body)`` for every commit this merge brought in.

    PER-COMMIT rather than one concatenated blob, because a caller has to decide
    commit by commit whether a body is still worth reading: a back-merge brings in
    work whose events already landed, and re-deriving those trailers would credit
    the merge with resolving them.

    The merge commit itself is reachable from `<merge>` and is filtered out here —
    its own body is the caller's, not incoming work.

    Fails safe: any git error returns `[]` rather than raising into the caller.
    """
    out = _run_git(
        [
            "git",
            "log",
            "-z",
            "--format=%H%x1f%B",
            merge_hash,
            "--not",
            f"{merge_hash}^1",
        ],
        cwd,
    )
    if not out:
        return []
    pairs: list[tuple[str, str]] = []
    for record in out.split("\0"):
        # NUL between records, and the FIRST `\x1f` within one. Both choices are
        # about a commit BODY being untrusted input to this parse:
        #
        #   * `-z` makes git separate records with NUL, which a commit object
        #     cannot contain — git rejects it. An ASCII control byte like `\x1e`
        #     CAN appear in a message, so framing on one let a body inject a whole
        #     record. That mattered because the caller skips commits whose event is
        #     recorded, and a forged hash is absent from the log BY CONSTRUCTION —
        #     so an injected record smuggled its trailers past the filter every
        #     time. Validating the hash as 40 hex does NOT close that: a body can
        #     spell 40 hex characters as easily as any others (measured — the test
        #     for this failed against exactly that guard).
        #   * `partition` takes the FIRST `\x1f`, and the hash is emitted before the
        #     body, so a `\x1f` inside a message lands in the body half where it is
        #     harmless rather than truncating the hash.
        commit_hash, sep, body = record.strip().partition("\x1f")
        if (
            not sep
            or commit_hash == merge_hash
            or not _OBJECT_NAME_RE.match(commit_hash)
        ):
            continue
        pairs.append((commit_hash, body))
    return pairs
