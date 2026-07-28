#!/usr/bin/env python3
"""Archive sprint.json into sprints/, and read the newest one back.

Sibling module to sprint_store.py — sprint_store.py is at the 500-line cap,
so archive() lives here instead of growing that file. Mirrors
execution_plan_store.archive() exactly.

Reading is here too, with the writing, because the two share one contract:
what `archive()` names is what `load_latest()` has to find again.
"""

import json
import re
from pathlib import Path

from archive import archive_json
from sprint_schema import SPRINT_FILENAME, validate_sprint

_ARCHIVE_GLOB = "sprint_*.json"

# Exactly what `archive_json` writes: `sprint_<YYYYMMDD>T<HHMMSS>[-N]`. The glob
# alone is too loose to ORDER by — a hand-dropped `sprint_backup.json` sorts
# above every real `sprint_2026...` name and would be read as the newest sprint.
# Names that do not match are ignored for "which is newest", not deleted: a
# stray in sprints/ is someone's backup, and `sprint_metrics` tolerates strays
# by design.
_ARCHIVE_NAME_RE = re.compile(r"^sprint_(\d{8}T\d{6})(?:-(\d+))?$")


class UnusableArchiveError(Exception):
    """The newest archive exists but cannot be used.

    Distinct from "there is no archive": the caller must NOT quietly fall back
    to an older one (see `load_latest`), and it has something specific to say.
    """


def archive(smm_dir: Path) -> Path | None:
    """Move sprint.json to sprints/ with a timestamp.

    Returns the archived file path, or None if no sprint exists.
    """
    return archive_json(smm_dir, SPRINT_FILENAME, "sprints", "sprint")


def _sort_key(match: re.Match[str]) -> tuple[str, int]:
    """Order two archive names by when they were written.

    Plain filename order is WRONG for a same-second collision: `archive_json`
    appends `-1`, `-2`, ... and `-` (0x2D) sorts before `.` (0x2E), so the
    unsuffixed FIRST archive would outrank the `-1` that came after it. Compare
    the timestamp as text and the collision index as a NUMBER, so `-10` also
    lands after `-9`.
    """
    return (match.group(1), int(match.group(2) or 0))


def newest_path(smm_dir: Path) -> Path | None:
    """Path of the most recently archived sprint, or None if there is none.

    Public because the carry-over reader has to TELL the caller where the
    stories came from: an archived sprint holds each story's acceptance
    criteria and file_domain, and nothing else can reach them once sprint.json
    has been moved away.
    """
    sprints_dir = smm_dir / "sprints"
    if not sprints_dir.is_dir():
        return None
    try:
        named = [
            (m, p)
            for p in sprints_dir.glob(_ARCHIVE_GLOB)
            if (m := _ARCHIVE_NAME_RE.match(p.stem)) is not None
        ]
    except OSError:
        return None
    if not named:
        return None
    return max(named, key=lambda pair: _sort_key(pair[0]))[1]


def load_latest(smm_dir: Path) -> dict | None:
    """The newest archived sprint, or None when there is no archive at all.

    Raises `UnusableArchiveError` when the newest archive is present but
    unreadable or schema-invalid. It deliberately does NOT fall back to the one
    before it. An earlier attempt did, reasoning that the alternative was
    "carry nothing forward" — but the actual alternative is carrying the WRONG
    sprint's list: a review reproduced a truncated sprint-002 archive causing
    sprint-001's deferred story to be offered as carry-over, a story sprint-002
    had already finished, while sprint-002's real leftover went unmentioned.
    Silently substituting older history is the failure this reader exists to
    prevent, not a degraded form of success.

    Validation is the same `validate_sprint` the live loader uses, not a bare
    `isinstance(data, dict)` — every caller goes on to index `sprint["stories"]`
    and `story["status"]`, so a parseable-but-shapeless object only moves the
    failure downstream into a KeyError. Budget enforcement is off: an archive is
    a historical record, and refusing to read one because it outgrew today's
    limit would lose real carry-over.
    """
    path = newest_path(smm_dir)
    if path is None:
        return None
    # encoding pinned, like every sibling reader: the default is locale-derived,
    # and a UnicodeDecodeError here is a ValueError that would otherwise read as
    # corruption in a file that is perfectly well-formed UTF-8.
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UnusableArchiveError(f"cannot read {path.name}: {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise UnusableArchiveError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise UnusableArchiveError(f"{path.name} does not hold a sprint object")
    errors = validate_sprint(data, enforce_budget=False)
    if errors:
        raise UnusableArchiveError(
            f"{path.name} is schema-invalid: {'; '.join(errors)}"
        )
    return data
