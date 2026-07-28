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
import glob_translator

_EM_DASH = "—"
# The convention is "path — description" (em-dash); ASCII " -- " and " - " are
# both common deviations. All three end the path portion. A leaked description
# once crashed a hook by feeding prose to the glob compiler — and an
# UNRECOGNIZED separator is worse than a crash, because it fails silently: the
# whole entry becomes the path, the declared file matches nothing, and
# `validate-domain` reports drift on a file that is plainly declared. The single
# hyphen was the form that did that (concern dd9ddb62ec3f).
#
# ASCII separators require a LEADING space and must be followed by whitespace or
# end-of-entry, so a hyphen inside a filename (`pre-commit-hook.py`) is never a
# separator. `--` precedes `-` in the alternation so the longer form wins where
# both could match. The em dash keeps its bare search — it needs no surrounding
# spaces and cannot occur inside a path.
_ASCII_DESC_SEP_RE = re.compile(r"\s(?:--|-)(?=\s|$)")


def entry_to_paths(entry: str) -> list[str]:
    """Split one file_domain entry into its declared path(s).

    An entry is "path — description", "path -- description",
    "path - description", or just "path"; multiple paths may be comma-joined
    ("a.ts, b.ts — ..."). The description (after the earliest separator of any
    of the three forms) is stripped before splitting on commas, so a comma
    inside the description never spawns a phantom path. Returns cleaned,
    non-empty path strings.
    """
    seps = [entry.index(_EM_DASH)] if _EM_DASH in entry else []
    ascii_match = _ASCII_DESC_SEP_RE.search(entry)
    if ascii_match is not None:
        seps.append(ascii_match.start())
    head = entry[: min(seps)] if seps else entry  # earliest separator wins
    return [p.strip() for p in head.split(",") if p.strip()]


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
    """Translate a shell-style glob to a regex (delegates to shared primitive)."""
    return glob_translator.glob_to_regex(pattern)


@functools.lru_cache(maxsize=256)
def _compile_glob(pattern: str) -> re.Pattern[str]:
    """Compile a glob pattern to a regex once and cache.

    `resolve_dominant_story` is on the pre-commit hot path — same patterns
    recompile on every commit without this cache.

    Degrades gracefully on a malformed glob: free-text file_domain prose
    (e.g. "...effects[].damage...") can produce an invalid regex — a bare
    `[]` is an unterminated character set. Rather than let re.error escape
    and crash the caller (it took down the SessionStart retrospective hook),
    fall back to matching the pattern as a literal. The bad entry is not a
    real path, so it simply matches nothing real instead of raising.
    """
    try:
        return re.compile(_glob_to_regex(pattern))
    except re.error:
        return re.compile(re.escape(pattern))


def extract_file_domain_paths(
    file_domain: list[str],
    candidate_files: Iterable[str] | None = None,
    cwd: Path | str | None = None,
) -> set[str]:
    """Extract file paths from file_domain entries, expanding any globs.

    Entries are "path — description" (em-dash convention), "path --
    description" or "path - description" (both common ASCII deviations), or
    just "path"; several paths may be comma-joined in one entry. See
    `entry_to_paths`. When a path
    contains glob metacharacters (`*`, `?`, `[...]`) the entry expands to
    matching files: against `candidate_files` via fnmatch-style regex when
    provided
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
        for path in entry_to_paths(entry):
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
