#!/usr/bin/env python3
"""What a merge brought in: the commits reachable from it but not from `^1`.

Split from `commits.py`, which crossed its 450-line sub-cap when the per-commit
reader arrived. One job, asked by every merge emitter, so it lives here rather
than beside every other git read.

`<merge> --not <merge>^1`, NOT `^1..^2`. The two agree for an ordinary two-parent
merge and diverge for an octopus: `^1..^2` sees only the second parent's work, so a
`git merge feat-a feat-b` silently dropped feat-b's commits while the merge still
counted as one. Asking for "reachable from the merge, not from the first parent"
covers every incoming parent by construction.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from commits import _run_git

# A full git object name. Anchored at both ends, because its whole job is to
# refuse a hash-shaped span a commit BODY supplied — see the parse below.
_OBJECT_NAME_RE = re.compile(r"^[0-9a-f]{40}$")


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
