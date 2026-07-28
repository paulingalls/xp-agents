#!/usr/bin/env python3
"""Is a concern PROVABLY about code a close diff does not touch?

Extracted from `smm_count.py` (500-line cap) because the rule grew a second
kind of evidence — the close diff, and the working tree — and it is the only
place in the count path that decides to DROP a concern from a merge gate.

Every predicate here is one-directional: it may only ever narrow the set of
concerns that count, and only on positive evidence. Absence of evidence
(unreadable entry, missing path, no diff) leaves the concern counted.
"""

import sys
from pathlib import Path


def normalize_repo_path(raw: str) -> str:
    """Normalise a repo-relative path for comparison — PURE STRING work.

    Deliberately NOT `scripts/worktree.py`'s normalize_path: that one shells out
    to git per call and resolves against cwd. This runs once per (recorded file,
    diff path) pair, has no repo to resolve against, and must stay language- and
    filesystem-agnostic (it compares bytes, never syntax or file types). The
    small duplication is the price of those three properties.
    """
    path = raw.strip().rstrip("/")
    while path.startswith("./"):
        path = path[2:]
    return path


def load_diff_paths(spec: str | None) -> set[str]:
    """Parse newline-separated repo-relative paths from a file, or stdin ("-").

    Returns an EMPTY set for every degraded case — no spec, unreadable path,
    undecodable bytes, blank content — because empty and absent MUST behave
    identically at the call site (see smm_count._cmd_count_concerns). Swallowing
    the read error here is safe only because of that: the caller notes the
    degradation on stderr and falls back to counting everything.

    UnicodeDecodeError is caught for the same reason OSError is: a path list a
    non-UTF-8 filename made undecodable must degrade to counting everything, not
    crash the gate query into an empty `$(...)` capture. Discarding the whole
    list beats decoding it lossily — a mangled path silently matches nothing,
    which is the fail-OPEN direction.
    """
    if not spec:
        return set()
    try:
        raw = sys.stdin.read() if spec == "-" else Path(spec).read_text()
    except (OSError, UnicodeDecodeError):
        return set()
    return {p for p in (normalize_repo_path(line) for line in raw.splitlines()) if p}


def _intersects_diff(entry: str, diff_paths: set[str]) -> bool:
    """True when a concern's recorded path names something in the close diff.

    Exact match, or *entry* is a DIRECTORY PREFIX of a diff path — a concern
    pinned at directory granularity covers the files beneath it. No globbing.

    An entry containing no "/" also matches any diff path's BASENAME.
    Non-repo-relative entries exist in real logs (`files:['pre_tool_bash.py']`
    for plugins/xp-agents/scripts/pre_tool_bash.py), and under exact-plus-prefix
    alone such an entry could never intersect ANY diff — so its concern would be
    excluded from EVERY scoped gate. The fallback errs toward counting.
    """
    if entry in diff_paths:
        return True
    prefix = entry + "/"
    if any(path.startswith(prefix) for path in diff_paths):
        return True
    if "/" in entry:
        return False
    return any(path.rsplit("/", 1)[-1] == entry for path in diff_paths)


def _is_repo_relative(path: str) -> bool:
    """False for an entry that cannot be COMPARED to a repo-relative diff path.

    An absolute (`/…`, `~/…`) or parent-escaping (`../…`) entry names its file in
    the wrong vocabulary: `git diff --name-only` always emits repo-relative
    paths, so such an entry can never match one, and exact-plus-prefix matching
    would read that as PROOF of irrelevance and drop the concern from every
    scoped gate. It is unreadable evidence, like a blank or non-string entry —
    the same class the slash-less basename fallback covers from the other side.
    """
    return not path.startswith(("/", "~")) and ".." not in path.split("/")


def _names_existing_code(root: Path, entry: str) -> bool:
    """Does *entry* name something that EXISTS in the working tree at *root*?

    The load-bearing half of "provably about other code". Outside-the-diff is
    proof of irrelevance only for a file that is THERE and simply was not
    touched. A path that does not exist is the opposite: the commonest reason a
    review names one is that it is MISSING — "no acceptance test exists for the
    new gate", recorded against the test file nobody wrote. That path can never
    appear in `git diff --name-only` precisely BECAUSE the work was skipped, so
    the diff comparison reads the absence of the work as proof the finding is
    irrelevant, and the gate drops the one concern that should stop the merge.

    `lexists`-style semantics via `is_symlink() or exists()`: a broken symlink
    still names a real tracked entry. Any OSError (unsearchable directory, a
    path too long, a decoding failure on a non-UTF-8 name) answers False, which
    keeps the concern counted — the fail-closed direction.

    Cost, stated plainly: a concern about a file only a sibling worktree's
    unmerged branch contains now counts against this close, where before it was
    dropped. That is a visible, overridable abort recommendation rather than a
    silent merge, and `close_cycle_id` on the concern still bypasses the whole
    rule.
    """
    candidate = root / entry
    try:
        return candidate.is_symlink() or candidate.exists()
    except OSError:
        return False


def provably_outside_diff(event: dict, diff_paths: set[str], root: Path) -> bool:
    """True IFF the concern names files that all EXIST and none of which
    intersect the close diff.

    Every early False is a fail-closed default. No `files` (or an empty list)
    proves nothing about relevance. A non-string, blank, non-repo-relative, or
    non-existent entry is unreadable evidence, not absent evidence, so it too
    keeps the concern on the floor. Only a fully-readable, fully-comparable,
    fully-present file list that misses the diff entirely is proof.

    Caller must have established diff_paths is non-empty — against an empty set
    "no entry intersects" is vacuously true, which is the one way the rule fails
    OPEN.
    """
    files = event.get("files")
    if not isinstance(files, list) or not files:
        return False
    for entry in files:
        if not isinstance(entry, str):
            return False
        normalized = normalize_repo_path(entry)
        if not normalized or not _is_repo_relative(normalized):
            return False
        if not _names_existing_code(root, normalized):
            return False
        if _intersects_diff(normalized, diff_paths):
            return False
    return True
