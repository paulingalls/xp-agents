#!/usr/bin/env python3
"""What a merge brought in: the commits reachable from it but not from `^1`.

Split from `commits.py`, which crossed its 450-line sub-cap when the per-commit
reader arrived. One job, two shapes of the same question — asked by both merge
emitters — so they live together rather than beside every other git read.

`<merge> --not <merge>^1`, NOT `^1..^2`. The two agree for an ordinary two-parent
merge and diverge for an octopus: `^1..^2` sees only the second parent's work, so a
`git merge feat-a feat-b` silently dropped feat-b's commits while the merge still
counted as one. Asking for "reachable from the merge, not from the first parent"
covers every incoming parent by construction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from commits import _run_git


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
        ["git", "log", "--format=%H%x1f%B%x1e", merge_hash, "--not", f"{merge_hash}^1"],
        cwd,
    )
    if not out:
        return []
    pairs: list[tuple[str, str]] = []
    for record in out.split("\x1e"):
        commit_hash, sep, body = record.strip().partition("\x1f")
        if not sep or commit_hash == merge_hash:
            continue
        pairs.append((commit_hash, body))
    return pairs


def merged_range_bodies(cwd: str, merge_hash: str) -> str:
    """Every incoming body, concatenated — for a caller that wants no per-commit
    decision. The close-cycle emitter's range is its own story's commits, bounded
    by construction, so it has nothing to filter on.

    Expressed over `merged_range_commits` rather than its own `git log`: one range
    definition, so the octopus fix above reaches this caller too.
    """
    return "\n".join(body for _, body in merged_range_commits(cwd, merge_hash))
