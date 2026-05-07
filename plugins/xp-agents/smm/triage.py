#!/usr/bin/env python3
"""Shared triage helpers for concern/debt/question resolution.

Used by xp-work-selection and xp-accept preloads to find unresolved
events and detect file overlap with commits.
"""

import functools
import glob as _glob
import re
from collections.abc import Iterable
from pathlib import Path

import event_schema

_EM_DASH = "—"


def find_unresolved(
    events: list[dict],
    event_type: str,
    resolved_ids: set[str],
) -> list[dict]:
    """Return unresolved events of a given type, newest first."""
    unresolved = [
        e
        for e in events
        if e.get("type") == event_type and e.get("id") not in resolved_ids
    ]
    return sorted(unresolved, key=lambda e: e.get("ts", ""), reverse=True)


def find_overlapping_commits(
    concern: dict,
    events: list[dict],
) -> list[dict]:
    """Find commit events whose files overlap the concern's files.

    Only considers commits after the concern's timestamp.
    """
    concern_files = set(concern.get("files") or [])
    if not concern_files:
        return []
    concern_ts = concern.get("ts", "")

    overlapping = []
    for e in events:
        if e.get("type") != event_schema.EVENT_TYPE_COMMIT:
            continue
        if e.get("ts", "") <= concern_ts:
            continue
        commit_files = set(e.get("files") or [])
        if concern_files & commit_files:
            overlapping.append(e)
    return overlapping


def _glob_to_regex(pattern: str) -> str:
    """Translate a shell-style glob to a regex.

    Honors `**` as "zero or more path segments" (so `tests/**/*.py` matches
    `tests/a.py` and `tests/sub/a.py`); `*` and `?` stop at slashes; bracket
    classes pass through. `fnmatch.translate` would be reused if its `*`
    didn't cross slashes (it does), so `**`-recursion can't be expressed —
    hence the local translator.
    """
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i):
            out.append("(?:/.*)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            j = pattern.find("]", i)
            if j == -1:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                out.append(pattern[i : j + 1])
                i = j + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


@functools.lru_cache(maxsize=256)
def _compile_glob(pattern: str) -> re.Pattern[str]:
    """Compile a glob pattern to a regex once and cache.

    `resolve_dominant_story` is on the pre-commit hot path — same patterns
    recompile on every commit without this cache.
    """
    return re.compile(_glob_to_regex(pattern))


def extract_file_domain_paths(
    file_domain: list[str],
    candidate_files: Iterable[str] | None = None,
    cwd: Path | str | None = None,
) -> set[str]:
    """Extract file paths from file_domain entries, expanding any globs.

    Entries are "path — description" or just "path". When the path contains
    glob metacharacters (`*`, `?`, `[...]`) the entry expands to matching
    files: against `candidate_files` via fnmatch-style regex when provided
    (the cascade-analysis case — historical commits whose files may no
    longer exist on disk), otherwise via `pathlib.Path(cwd).glob`.

    `candidate_files` takes precedence over `cwd`: when candidates are
    supplied, glob entries match the in-memory iterable and `cwd` is
    unused. Cascade-analysis (`story_metrics._attribute_commits`) and
    concern triage (`concern_triage.find_concerns_for_story`) both ride
    this path.

    Raises ValueError when a glob entry is encountered with no
    `candidate_files` AND no `cwd` — eliminates the previous
    process-cwd-implicit foot-gun (concern edf2fc993f52). Literal-only
    file_domains continue to work without `cwd`.
    """
    paths: set[str] = set()
    candidates_list: list[str] | None = None  # materialized lazily on first glob
    glob_root = Path(cwd) if cwd is not None else None
    for entry in file_domain:
        path = (
            entry.split(_EM_DASH, 1)[0].strip() if _EM_DASH in entry else entry.strip()
        )
        if not path:
            continue
        if not _glob.has_magic(path):
            paths.add(path)
            continue
        if candidate_files is not None:
            if candidates_list is None:
                candidates_list = list(candidate_files)
            regex = _compile_glob(path)
            for cand in candidates_list:
                if regex.fullmatch(cand):
                    paths.add(cand)
        else:
            if glob_root is None:
                raise ValueError(
                    f"extract_file_domain_paths: glob entry {path!r} requires "
                    "candidate_files= or cwd= (no implicit-cwd fallback)"
                )
            # Normalize to paths RELATIVE TO `glob_root` so result shape
            # matches what callers passing literal paths produce.
            for match in glob_root.glob(path):
                paths.add(str(match.relative_to(glob_root)))
    return paths
